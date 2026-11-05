// Package settlement persists an exact purchase before any submission.
// It is transport independent and never creates replacement authorizations.
package settlement

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"syscall"

	"example.org/fairbind/protocol"
)

var ErrConflict = errors.New("persisted purchase or ledger conflict")

type Record struct {
	Version       int                       `json:"version"`
	Expected      protocol.ExpectedPurchase `json:"expected"`
	Authorization []byte                    `json:"authorization"`
	Confirmed     bool                      `json:"confirmed"`
}

// Ledger must read a consistent finalized purchase/key snapshot. Missing means
// no recorded settlement, not proof that no transaction is pending. Submit must
// submit the exact saved authorization to the at-most-once settlement contract.
// No implementation may translate an uncertain result into a fresh nonce/key.
type Ledger interface {
	Lookup(protocol.ExpectedPurchase) (*protocol.RecordedPurchase, protocol.Bytes32, error)
	Submit(protocol.ExpectedPurchase, []byte) error
}

func locked(path string, fn func() error) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	f, err := os.OpenFile(path+".lock", os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return err
	}
	defer f.Close()
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		return err
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	return fn()
}
func read(path string) (Record, error) {
	var r Record
	data, err := os.ReadFile(path)
	if err != nil {
		return r, err
	}
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if err = d.Decode(&r); err != nil {
		return r, err
	}
	if r.Version != 1 || len(r.Authorization) == 0 || r.Expected.Nonce == (protocol.Bytes32{}) || r.Expected.KeyID == (protocol.Bytes32{}) {
		return r, errors.New("invalid journal")
	}
	// Reject any second JSON value or trailing garbage.
	var trailing any
	if err = d.Decode(&trailing); err == nil {
		return r, errors.New("trailing journal data")
	}
	if !errors.Is(err, io.EOF) {
		return r, err
	}
	return r, nil
}
func save(path string, r Record) error {
	data, err := json.Marshal(r)
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".purchase-*")
	if err != nil {
		return err
	}
	tmp := f.Name()
	defer os.Remove(tmp)
	if _, err = f.Write(data); err != nil {
		f.Close()
		return err
	}
	if err = f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	if err = os.Rename(tmp, path); err != nil {
		return err
	}
	dir, err := os.Open(filepath.Dir(path))
	if err != nil {
		return err
	}
	defer dir.Close()
	return dir.Sync()
}

// Prepare commits the exact authorization before submission. Existing records
// are immutable except for confirmation. Concurrent users share an OS lock.
func Prepare(path string, expected protocol.ExpectedPurchase, authorization []byte) error {
	if len(authorization) == 0 || expected.Nonce == (protocol.Bytes32{}) || expected.KeyID == (protocol.Bytes32{}) {
		return errors.New("missing identity or authorization")
	}
	return locked(path, func() error {
		r, err := read(path)
		if err == nil {
			if r.Expected != expected || !bytes.Equal(r.Authorization, authorization) {
				return ErrConflict
			}
			return nil
		}
		if !errors.Is(err, os.ErrNotExist) {
			return err
		}
		return save(path, Record{Version: 1, Expected: expected, Authorization: append([]byte(nil), authorization...)})
	})
}

// Resume first reconciles, then (only if absent) resubmits the saved purchase.
// A submission error remains uncertain: its return is not a rollback assertion.
// A later Resume looks up the ledger again, including after process death.
func Resume(path string, ledger Ledger) error {
	return locked(path, func() error {
		r, err := read(path)
		if err != nil {
			return err
		}
		lookup := func() (protocol.ReconcileStatus, error) {
			byNonce, key, err := ledger.Lookup(r.Expected)
			if err != nil {
				return 0, err
			}
			return protocol.Reconcile(r.Expected, byNonce, key), nil
		}
		status, err := lookup()
		if err != nil {
			return err
		}
		if status == protocol.ReconcileConflict {
			return ErrConflict
		}
		if status == protocol.ReconcileConfirmed {
			r.Confirmed = true
			return save(path, r)
		}
		if r.Confirmed {
			return fmt.Errorf("%w: finalized record disappeared", ErrConflict)
		}
		if err = ledger.Submit(r.Expected, append([]byte(nil), r.Authorization...)); err != nil {
			return err
		}
		status, err = lookup()
		if err != nil {
			return err
		}
		if status == protocol.ReconcileConflict {
			return ErrConflict
		}
		if status != protocol.ReconcileConfirmed {
			return errors.New("settlement remains uncertain")
		}
		r.Confirmed = true
		return save(path, r)
	})
}
