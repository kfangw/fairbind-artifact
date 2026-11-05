package verifier

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"syscall"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/ledger"
)

// Status is the worker's view of one assignment. The outbox, not this file,
// decides whether a broadcast may happen: the worker always consults
// Outbox.Load before submitting, so a stale status can never cause a resend.
type Status string

const (
	StatusPrepared  Status = "prepared"  // signed record saved; no broadcast attempted
	StatusSubmitted Status = "submitted" // broadcast acknowledged with a transaction hash
	StatusUncertain Status = "uncertain" // attempt marker exists; outcome unknown
	StatusConfirmed Status = "confirmed" // VerdictSubmitted observed at a finalized block
	StatusReverted  Status = "reverted"  // our transaction reverted at a finalized block
	StatusMissed    Status = "missed"    // finalized case moved on without our verdict
	StatusExpired   Status = "expired"   // deadline too close; nothing was broadcast
	StatusSkipped   Status = "skipped"   // not serviceable by this configuration
)

func (s Status) terminal() bool {
	switch s {
	case StatusConfirmed, StatusReverted, StatusMissed, StatusExpired, StatusSkipped:
		return true
	}
	return false
}

func (s Status) inFlight() bool { return s == StatusSubmitted || s == StatusUncertain }

// Entry records one assignment (nonce, stage, attempt, verifier).
type Entry struct {
	Nonce        string `json:"nonce"`
	Stage        uint8  `json:"stage"`
	Attempt      uint8  `json:"attempt"`
	VerifierID   uint32 `json:"verifierId"`
	JudgeDue     uint64 `json:"judgeDue"`
	FromBlock    uint64 `json:"fromBlock"`
	Verdict      uint8  `json:"verdict,omitempty"`
	EvidenceHash string `json:"evidenceHash,omitempty"`
	Tx           string `json:"tx,omitempty"`
	Status       Status `json:"status"`
	Note         string `json:"note,omitempty"`
	// Worst-path directive progress of the assignment (directed.go).
	ServeRequested bool `json:"serveRequested,omitempty"`
	Escalated      bool `json:"escalated,omitempty"`
	Disclosed      bool `json:"disclosed,omitempty"`
}

// State is persisted as state.json in the state directory.
type State struct {
	Version int               `json:"version"`
	Cursor  uint64            `json:"cursor"` // next block to scan for assignments
	Watch   []string          `json:"watch"`  // nonces with possible work
	Entries map[string]*Entry `json:"entries"`
}

func entryKey(nonce protocol.Bytes32, stage, attempt uint8, verifierID uint32) string {
	return fmt.Sprintf("%x-%d-%d-%d", nonce, stage, attempt, verifierID)
}

func assignmentKey(a ledger.Assignment) string {
	return entryKey(a.Snapshot.Nonce, a.Stage, a.Attempt, a.VerifierID)
}

// Store owns state.json and an exclusive lock that prevents two workers from
// sharing a state directory.
type Store struct {
	dir  string
	lock *os.File
	S    State
}

func OpenStore(dir string) (*Store, error) {
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(filepath.Join(dir, "worker.lock"), os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		return nil, fmt.Errorf("state directory in use by another worker")
	}
	s := &Store{dir: dir, lock: f, S: State{Version: 1, Entries: map[string]*Entry{}}}
	raw, err := os.ReadFile(filepath.Join(dir, "state.json"))
	if errors.Is(err, fs.ErrNotExist) {
		return s, nil
	}
	if err == nil {
		err = json.Unmarshal(raw, &s.S)
	}
	if err == nil && s.S.Version != 1 {
		err = fmt.Errorf("unsupported state version")
	}
	if err != nil {
		s.Close()
		return nil, fmt.Errorf("state.json: %w", err)
	}
	if s.S.Entries == nil {
		s.S.Entries = map[string]*Entry{}
	}
	return s, nil
}

// Close releases the lock. A process exit releases it as well.
func (s *Store) Close() error {
	if s.lock == nil {
		return nil
	}
	syscall.Flock(int(s.lock.Fd()), syscall.LOCK_UN)
	err := s.lock.Close()
	s.lock = nil
	return err
}

// Save writes state.json atomically (temporary file, fsync, rename, directory fsync).
func (s *Store) Save() error {
	sort.Strings(s.S.Watch)
	raw, err := json.MarshalIndent(s.S, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(s.dir, ".state-")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if _, err = f.Write(append(raw, '\n')); err == nil {
		err = f.Sync()
	}
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		return err
	}
	if err = os.Rename(name, filepath.Join(s.dir, "state.json")); err != nil {
		return err
	}
	d, err := os.Open(s.dir)
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}

func (s *Store) watch(nonce protocol.Bytes32) {
	h := hex32(nonce)
	for _, w := range s.S.Watch {
		if w == h {
			return
		}
	}
	s.S.Watch = append(s.S.Watch, h)
}

func (s *Store) unwatch(nonce protocol.Bytes32) {
	h := hex32(nonce)
	out := s.S.Watch[:0]
	for _, w := range s.S.Watch {
		if w != h {
			out = append(out, w)
		}
	}
	s.S.Watch = out
}

func (s *Store) entriesFor(nonce protocol.Bytes32) []*Entry {
	var out []*Entry
	h := hex32(nonce)
	keys := make([]string, 0, len(s.S.Entries))
	for k := range s.S.Entries {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if e := s.S.Entries[k]; e.Nonce == h {
			out = append(out, e)
		}
	}
	return out
}
