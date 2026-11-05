package keeper

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"syscall"
)

type TrackedPurchase struct {
	SellerID  uint32 `json:"sellerId"`
	BondID    uint32 `json:"bondId"`
	ProfileID uint32 `json:"profileId"`
	Epoch     uint32 `json:"epoch"`
}

type TrackedEpoch struct {
	SellerID  uint32 `json:"sellerId"`
	ProfileID uint32 `json:"profileId"`
	Epoch     uint32 `json:"epoch"`
}

// SentRecord marks an action broadcast (or about to be broadcast) at a
// finalized block. Tx is zero when the process stopped before the node
// acknowledged the transaction.
type SentRecord struct {
	Action string `json:"action"`
	At     uint64 `json:"at"`
	Tx     string `json:"tx,omitempty"`
}

// State is everything the keeper needs after a restart.
type State struct {
	Version   int                        `json:"version"`
	Started   bool                       `json:"started"`
	Scanned   uint64                     `json:"scanned"`
	Purchases map[string]TrackedPurchase `json:"purchases"`
	Epochs    map[string]TrackedEpoch    `json:"epochs"`
	Bonds     map[string]uint32          `json:"bonds"`
	Sent      map[string]SentRecord      `json:"sent"`
}

func newState() State {
	return State{Version: 1, Purchases: map[string]TrackedPurchase{}, Epochs: map[string]TrackedEpoch{},
		Bonds: map[string]uint32{}, Sent: map[string]SentRecord{}}
}

func (s State) clone() State {
	c := newState()
	c.Started, c.Scanned = s.Started, s.Scanned
	for k, v := range s.Purchases {
		c.Purchases[k] = v
	}
	for k, v := range s.Epochs {
		c.Epochs[k] = v
	}
	for k, v := range s.Bonds {
		c.Bonds[k] = v
	}
	for k, v := range s.Sent {
		c.Sent[k] = v
	}
	return c
}

// Store persists State in one JSON file. Every update is written to a
// temporary file, synced and renamed, so a crash leaves either the previous or
// the new state. An exclusive lock prevents two keepers sharing one file.
type Store struct {
	path  string
	mu    sync.Mutex
	state State
	lock  *os.File
}

// OpenStore loads or creates the state file. Pass an empty path for an
// in-memory store (tests only).
func OpenStore(path string) (*Store, error) {
	s := &Store{path: path, state: newState()}
	if path == "" {
		return s, nil
	}
	lock, err := os.OpenFile(path+".lock", os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW, 0o600)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		lock.Close()
		return nil, fmt.Errorf("state file is in use: %w", err)
	}
	s.lock = lock
	raw, err := os.ReadFile(path)
	switch {
	case os.IsNotExist(err):
		return s, nil
	case err != nil:
		s.Close()
		return nil, err
	}
	loaded := newState()
	if err = json.Unmarshal(raw, &loaded); err != nil || loaded.Version != 1 {
		s.Close()
		return nil, fmt.Errorf("invalid keeper state file")
	}
	s.state = loaded.clone()
	return s, nil
}

func (s *Store) Close() error {
	if s.lock == nil {
		return nil
	}
	syscall.Flock(int(s.lock.Fd()), syscall.LOCK_UN)
	err := s.lock.Close()
	s.lock = nil
	return err
}

// State returns a copy of the current state.
func (s *Store) State() State {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.state.clone()
}

// Update applies f and persists the result before returning.
func (s *Store) Update(f func(*State)) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	next := s.state.clone()
	f(&next)
	if s.path != "" {
		if err := writeAtomic(s.path, next); err != nil {
			return err
		}
	}
	s.state = next
	return nil
}

func writeAtomic(path string, st State) error {
	raw, err := json.MarshalIndent(st, "", "  ")
	if err != nil {
		return err
	}
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, ".keeper-state-*")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name)
	if _, err = tmp.Write(raw); err == nil {
		err = tmp.Sync()
	}
	if cerr := tmp.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		return err
	}
	if err = os.Rename(name, path); err != nil {
		return err
	}
	d, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}
