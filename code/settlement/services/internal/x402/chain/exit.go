package chain

import "context"

// Seller and bond status values beyond SellerActive (contract-interface-v1
// section 2).
const (
	SellerExiting uint8 = 4
	SellerExited  uint8 = 5
	BondActive    uint8 = 1
	BondExiting   uint8 = 2
	BondExited    uint8 = 3

	sigRequestSellerExit  = "requestSellerExit(uint32)"
	sigFinalizeSellerExit = "finalizeSellerExit(uint32)"
	sigRequestBondExit    = "requestBondExit(uint32)"
	sigFinalizeBondExit   = "finalizeBondExit(uint32)"
)

// Exiter is the seller owner's side of seller and bond exit
// (contract-interface-v1 section 9). A call that is not yet allowed returns a
// *RevertError (ExitNotReady, SellerInactive, BondNotActive) without a
// transaction: the RPC client simulates every call before sending it.
type Exiter interface {
	RequestSellerExit(ctx context.Context, sellerID uint32) (Hash, error)
	FinalizeSellerExit(ctx context.Context, sellerID uint32) (Hash, error)
	RequestBondExit(ctx context.Context, bondID uint32) (Hash, error)
	FinalizeBondExit(ctx context.Context, bondID uint32) (Hash, error)
}

func (r *RPC) RequestSellerExit(ctx context.Context, id uint32) (Hash, error) {
	return r.send(ctx, call(sigRequestSellerExit, st(u(uint64(id)))))
}

func (r *RPC) FinalizeSellerExit(ctx context.Context, id uint32) (Hash, error) {
	return r.send(ctx, call(sigFinalizeSellerExit, st(u(uint64(id)))))
}

func (r *RPC) RequestBondExit(ctx context.Context, id uint32) (Hash, error) {
	return r.send(ctx, call(sigRequestBondExit, st(u(uint64(id)))))
}

func (r *RPC) FinalizeBondExit(ctx context.Context, id uint32) (Hash, error) {
	return r.send(ctx, call(sigFinalizeBondExit, st(u(uint64(id)))))
}

var _ Exiter = (*RPC)(nil)

// The fake models the owner checks, the status order and the retention wait
// of both exits. It does not model the frozen-pool, pending-trigger or
// deferred-balance conditions, which a test sets with FreezeBond.

func (c *fakeClient) RequestSellerExit(_ context.Context, id uint32) (Hash, error) {
	return c.f.tx("RequestSellerExit", func() error {
		s, ok := c.f.sellers[id]
		if !ok || s.Owner != c.from {
			return revert("Unauthorized")
		}
		if s.Status == SellerExiting || s.Status == SellerExited || s.Status == 0 {
			return revert("SellerInactive")
		}
		s.Status = SellerExiting
		c.f.sellers[id] = s
		c.f.exitAt[exitKey{seller: id}] = c.f.block + uint64(c.f.profiles[s.ProfileID].RetentionBlocks)
		return nil
	})
}

func (c *fakeClient) FinalizeSellerExit(_ context.Context, id uint32) (Hash, error) {
	return c.f.tx("FinalizeSellerExit", func() error {
		s, ok := c.f.sellers[id]
		if !ok || s.Owner != c.from {
			return revert("Unauthorized")
		}
		b := c.f.bonds[s.BondID]
		if s.Status != SellerExiting || c.f.block < c.f.exitAt[exitKey{seller: id}] ||
			b.FreezeState == FreezeFrozen || b.FreezeState == FreezeClaimOpen {
			return revert("ExitNotReady")
		}
		s.Status = SellerExited
		c.f.sellers[id] = s
		return nil
	})
}

func (c *fakeClient) bondOwner(id uint32) bool {
	for _, s := range c.f.sellers {
		if s.BondID == id && s.Owner == c.from {
			return true
		}
	}
	return false
}

func (c *fakeClient) RequestBondExit(_ context.Context, id uint32) (Hash, error) {
	return c.f.tx("RequestBondExit", func() error {
		b, ok := c.f.bonds[id]
		if !ok || !c.bondOwner(id) {
			return revert("Unauthorized")
		}
		if b.Status != BondActive && b.Status != 0 {
			return revert("BondNotActive")
		}
		b.Status = BondExiting
		c.f.bonds[id] = b
		retention := uint64(0)
		for _, s := range c.f.sellers {
			if s.BondID == id {
				retention = uint64(c.f.profiles[s.ProfileID].RetentionBlocks)
			}
		}
		c.f.exitAt[exitKey{bond: id}] = c.f.block + retention
		return nil
	})
}

func (c *fakeClient) FinalizeBondExit(_ context.Context, id uint32) (Hash, error) {
	return c.f.tx("FinalizeBondExit", func() error {
		b, ok := c.f.bonds[id]
		if !ok || !c.bondOwner(id) {
			return revert("Unauthorized")
		}
		registered := false
		for _, s := range c.f.sellers {
			if s.BondID == id && s.Status != SellerExited {
				registered = true
			}
		}
		if b.Status != BondExiting || c.f.block < c.f.exitAt[exitKey{bond: id}] || registered ||
			b.FreezeState == FreezeFrozen || b.FreezeState == FreezeClaimOpen {
			return revert("ExitNotReady")
		}
		b.Status = BondExited
		c.f.bonds[id] = b
		return nil
	})
}

var _ Exiter = (*fakeClient)(nil)

// exitKey names a seller (bond 0) or a bond account (seller 0) whose exit the
// fake is timing.
type exitKey struct {
	seller, bond uint32
}
