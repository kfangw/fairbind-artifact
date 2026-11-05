package settlement

import (
	"bytes"
	"encoding/json"
	"errors"
	"example.org/fairbind/protocol"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func purchase() protocol.ExpectedPurchase {
	return protocol.ExpectedPurchase{Nonce: protocol.Bytes32{1}, KeyID: protocol.Bytes32{2}, Value: 10}
}

type memoryLedger struct {
	p                   *protocol.RecordedPurchase
	count               int
	loseReply, failRead bool
	auth                []byte
}

func (m *memoryLedger) Lookup(e protocol.ExpectedPurchase) (*protocol.RecordedPurchase, protocol.Bytes32, error) {
	if m.failRead {
		return nil, protocol.Bytes32{}, errors.New("unavailable")
	}
	if m.p == nil {
		return nil, protocol.Bytes32{}, nil
	}
	return m.p, m.p.Nonce, nil
}
func (m *memoryLedger) Submit(e protocol.ExpectedPurchase, auth []byte) error {
	m.count++
	m.auth = auth
	m.p = &e
	if m.loseReply {
		return errors.New("reply lost")
	}
	return nil
}
func TestLostReplyReconcilesWithoutSecondSubmission(t *testing.T) {
	p := filepath.Join(t.TempDir(), "job.json")
	e := purchase()
	auth := []byte("exact signed bytes")
	if err := Prepare(p, e, auth); err != nil {
		t.Fatal(err)
	}
	m := &memoryLedger{loseReply: true}
	if Resume(p, m) == nil {
		t.Fatal("uncertain error expected")
	}
	if err := Resume(p, m); err != nil {
		t.Fatal(err)
	}
	if m.count != 1 || !bytes.Equal(m.auth, auth) {
		t.Fatal("replacement submission")
	}
}
func TestConflictsAndLookupFailureFailClosed(t *testing.T) {
	p := filepath.Join(t.TempDir(), "job.json")
	e := purchase()
	Prepare(p, e, []byte("auth"))
	other := e
	other.Value++
	if !errors.Is(Prepare(p, other, []byte("auth")), ErrConflict) {
		t.Fatal("identity replacement")
	}
	if !errors.Is(Prepare(p, e, []byte("new")), ErrConflict) {
		t.Fatal("authorization replacement")
	}
	m := &memoryLedger{failRead: true}
	if Resume(p, m) == nil || m.count != 0 {
		t.Fatal("lookup failure submitted")
	}
	m.failRead = false
	m.p = &other
	if !errors.Is(Resume(p, m), ErrConflict) || m.count != 0 {
		t.Fatal("ledger conflict submitted")
	}
}
func TestCorruptJournalIsNotOverwritten(t *testing.T) {
	p := filepath.Join(t.TempDir(), "job.json")
	os.WriteFile(p, []byte("broken"), 0600)
	if Prepare(p, purchase(), []byte("auth")) == nil {
		t.Fatal("overwrote corruption")
	}
	b, _ := os.ReadFile(p)
	if string(b) != "broken" {
		t.Fatal("corruption lost")
	}
}

// A separate process simulates a finalized ledger write followed by process
// death before the submission acknowledgement. This fake ledger is test-only.
type diskLedger struct {
	path  string
	crash bool
}

func (d diskLedger) Lookup(e protocol.ExpectedPurchase) (*protocol.RecordedPurchase, protocol.Bytes32, error) {
	b, err := os.ReadFile(d.path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, protocol.Bytes32{}, nil
	}
	if err != nil {
		return nil, protocol.Bytes32{}, err
	}
	var r protocol.RecordedPurchase
	if err = json.Unmarshal(b, &r); err != nil {
		return nil, protocol.Bytes32{}, err
	}
	return &r, r.Nonce, nil
}
func (d diskLedger) Submit(e protocol.ExpectedPurchase, auth []byte) error {
	if string(auth) != "same authorization" {
		return errors.New("changed bytes")
	}
	b, _ := json.Marshal(e)
	if err := os.WriteFile(d.path, b, 0600); err != nil {
		return err
	}
	f, err := os.OpenFile(d.path+".calls", os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	f.WriteString("submit\n")
	f.Close()
	if d.crash {
		os.Exit(23)
	}
	return nil
}
func TestProcessDeathAndRestart(t *testing.T) {
	if os.Getenv("FAIRBIND_JOURNAL_CHILD") == "1" {
		dir := os.Getenv("FAIRBIND_JOURNAL_DIR")
		err := Resume(filepath.Join(dir, "job.json"), diskLedger{filepath.Join(dir, "ledger.json"), os.Getenv("FAIRBIND_JOURNAL_CRASH") == "1"})
		if err != nil {
			t.Fatal(err)
		}
		return
	}
	dir := t.TempDir()
	Prepare(filepath.Join(dir, "job.json"), purchase(), []byte("same authorization"))
	run := func(crash string) error {
		c := exec.Command(os.Args[0], "-test.run=^TestProcessDeathAndRestart$")
		c.Env = append(os.Environ(), "FAIRBIND_JOURNAL_CHILD=1", "FAIRBIND_JOURNAL_DIR="+dir, "FAIRBIND_JOURNAL_CRASH="+crash)
		return c.Run()
	}
	var failure *exec.ExitError
	if err := run("1"); !errors.As(err, &failure) || failure.ExitCode() != 23 {
		t.Fatalf("expected injected process death: %v", err)
	}
	if err := run("0"); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(filepath.Join(dir, "ledger.json.calls"))
	if string(b) != "submit\n" {
		t.Fatal("duplicate submission after restart")
	}
	r, err := read(filepath.Join(dir, "job.json"))
	if err != nil || !r.Confirmed {
		t.Fatal("not confirmed", err)
	}
}

func TestFinalizedRecordDisappearanceCannotResubmit(t *testing.T) {
	path := filepath.Join(t.TempDir(), "job.json")
	if err := Prepare(path, purchase(), []byte("auth")); err != nil {
		t.Fatal(err)
	}
	ledger := &memoryLedger{}
	if err := Resume(path, ledger); err != nil {
		t.Fatal(err)
	}
	ledger.p = nil
	if !errors.Is(Resume(path, ledger), ErrConflict) || ledger.count != 1 {
		t.Fatal("resubmitted vanished finality")
	}
}

func TestTrailingDataAndUnknownFieldsFailClosed(t *testing.T) {
	for _, raw := range []string{`{"version":1,"unexpected":true}`, `{} {}`, `{} garbage`} {
		path := filepath.Join(t.TempDir(), "job.json")
		if err := os.WriteFile(path, []byte(raw), 0600); err != nil {
			t.Fatal(err)
		}
		ledger := &memoryLedger{}
		if Resume(path, ledger) == nil || ledger.count != 0 {
			t.Fatal("submitted malformed record")
		}
	}
}
