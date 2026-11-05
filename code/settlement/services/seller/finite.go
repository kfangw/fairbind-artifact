package seller

import (
	"context"
	"errors"
	"net/http"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/directive"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
)

// Finite-attack directive (experiments/controller/finiteattack.py, seller
// block; directive.FiniteAttack). The seller numbers its sales in the order it
// accepts their payments (the record is created before settlement) and cheats
// on the first CheatSales of them: it serves the route's Cheat handler, or the
// ordinary one when the route has none, and marks the record Cheat. Afterwards
// it serves honestly, stops selling, or stops selling and exits.

// ErrNotSelling is the error id of a purchase refused after a finite attack.
const ErrNotSelling = "seller_not_selling"

// AttackState is the persisted progress of a finite attack (meta/attack.json).
type AttackState struct {
	Version int `json:"version"`
	// Accepted counts the sales the seller accepted; the first CheatSales are
	// cheated.
	Accepted uint64     `json:"accepted"`
	Cheated  []x402.H32 `json:"cheated,omitempty"`
	// Refused counts purchases refused after the attack.
	Refused             uint64 `json:"refused,omitempty"`
	SellerExitRequested uint64 `json:"sellerExitRequestedBlock,omitempty"`
	BondExitRequested   uint64 `json:"bondExitRequestedBlock,omitempty"`
	SellerExited        uint64 `json:"sellerExitedBlock,omitempty"`
	BondExited          uint64 `json:"bondExitedBlock,omitempty"`
}

func (s *Seller) attackState() (AttackState, error) {
	var a AttackState
	_, err := s.store.Get("meta", "attack", &a)
	if a.Version == 0 {
		a.Version = 1
	}
	return a, err
}

// Attack returns the persisted finite-attack progress, for inspection.
func (s *Seller) Attack() (AttackState, error) {
	s.attackMu.Lock()
	defer s.attackMu.Unlock()
	return s.attackState()
}

// admitSale numbers a new sale under the finite attack. It returns whether the
// sale is cheated, or a refusal once the attack is over and the seller stops
// selling. Without the directive every sale is admitted and honest.
func (s *Seller) admitSale(rec *Record) (refuse bool, err error) {
	fa := s.opt.FiniteAttack
	if fa == nil {
		return false, nil
	}
	s.attackMu.Lock()
	defer s.attackMu.Unlock()
	a, err := s.attackState()
	if err != nil {
		return false, err
	}
	if a.Accepted >= fa.CheatSales && fa.StopsSelling() {
		a.Refused++
		return true, s.store.Put("meta", "attack", a)
	}
	if a.Accepted < fa.CheatSales {
		rec.Cheat = true
		a.Cheated = append(a.Cheated, rec.Nonce)
	}
	a.Accepted++
	return false, s.store.Put("meta", "attack", a)
}

// refusesOffers reports whether the seller answers new offers with a refusal.
func (s *Seller) refusesOffers() bool {
	fa := s.opt.FiniteAttack
	if !fa.StopsSelling() {
		return false
	}
	a, err := s.Attack()
	return err == nil && a.Accepted >= fa.CheatSales
}

func (s *Seller) refuse(w http.ResponseWriter) {
	w.Header().Set("Retry-After", "3600")
	fail(w, http.StatusServiceUnavailable, ErrNotSelling)
}

// handlerFor returns the handler that produces a record's response.
func handlerFor(route Route, cheat bool) Handler {
	if cheat && route.Cheat != nil {
		return route.Cheat
	}
	return route.Handler
}

// exitStep is the next exit call of a seller that attacked and exits.
type exitStep int

const (
	exitNone exitStep = iota
	exitRequestSeller
	exitRequestBond
	exitFinalizeSeller
	exitFinalizeBond
)

// nextExitStep orders the exit: request the registration's exit once every
// cheated sale is delivered, then the bond account's; finalize the
// registration, then the bond account, each once the contract admits it.
func nextExitStep(a AttackState, cheatSales uint64, cheatedDelivered bool) exitStep {
	switch {
	case uint64(len(a.Cheated)) < cheatSales || !cheatedDelivered:
		return exitNone
	case a.SellerExitRequested == 0:
		return exitRequestSeller
	case a.BondExitRequested == 0:
		return exitRequestBond
	case a.SellerExited == 0:
		return exitFinalizeSeller
	case a.BondExited == 0:
		return exitFinalizeBond
	}
	return exitNone
}

// exitDue carries out the exit of a seller whose directive ends the attack
// with request_exit; b is the latest block. A finalization the contract does
// not admit yet (ExitNotReady) is retried on a later pass.
func (s *Seller) exitDue(ctx context.Context, b uint64) error {
	fa := s.opt.FiniteAttack
	if fa == nil || fa.After != directive.AfterRequestExit {
		return nil
	}
	ex, ok := s.chain.(chain.Exiter)
	if !ok {
		return errors.New("the request_exit attack needs a chain client with exit calls")
	}
	s.attackMu.Lock()
	defer s.attackMu.Unlock()
	a, err := s.attackState()
	if err != nil {
		return err
	}
	delivered := true
	for _, n := range a.Cheated {
		rec, err := s.getRecord(protocol.Bytes32(n))
		if err != nil {
			return err
		}
		if rec == nil || rec.State != StateDelivered && rec.State != StatePruned {
			delivered = false
		}
	}
	for {
		step := nextExitStep(a, fa.CheatSales, delivered)
		var err error
		switch step {
		case exitNone:
			return nil
		case exitRequestSeller:
			_, err = ex.RequestSellerExit(ctx, s.view.SellerID)
		case exitRequestBond:
			_, err = ex.RequestBondExit(ctx, s.view.BondID)
		case exitFinalizeSeller:
			_, err = ex.FinalizeSellerExit(ctx, s.view.SellerID)
		case exitFinalizeBond:
			_, err = ex.FinalizeBondExit(ctx, s.view.BondID)
		}
		var rev *chain.RevertError
		switch {
		case err == nil:
		case chain.IsRevert(err, "ExitNotReady"):
			return nil // not admitted yet; retried on a later pass
		case errors.As(err, &rev) && (step == exitRequestSeller || step == exitRequestBond):
			// The contract refuses the request (for example a registration it
			// already moved on); record the attempt so the exit goes on.
			s.opt.Log.Printf("finite attack: exit step %d refused: %v", step, err)
		default:
			return err
		}
		switch step {
		case exitRequestSeller:
			a.SellerExitRequested = b + 1
		case exitRequestBond:
			a.BondExitRequested = b + 1
		case exitFinalizeSeller:
			a.SellerExited = b + 1
		case exitFinalizeBond:
			a.BondExited = b + 1
		}
		s.opt.Log.Printf("finite attack: exit step %d at block %d", step, b+1)
		if err := s.store.Put("meta", "attack", a); err != nil {
			return err
		}
	}
}
