package evidence

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"example.org/fairbind/protocol"
)

func TestStoreDurableReopenAndRepeat(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "objects")
	s, err := NewStore(dir, 4096)
	if err != nil {
		t.Fatal(err)
	}
	e, _ := vector(t)
	raw, want, err := Build(e)
	if err != nil {
		t.Fatal(err)
	}
	got, err := s.Put(raw)
	if err != nil || got != want {
		t.Fatal("put", err)
	}
	before, err := os.Stat(s.path(got))
	if err != nil {
		t.Fatal(err)
	}
	if before.Mode().Perm() != 0444 {
		t.Fatal("object is writable")
	}
	s, err = NewStore(dir, 4096)
	if err != nil {
		t.Fatal(err)
	}
	restored, err := s.Get(got)
	if err != nil || !bytes.Equal(raw, restored) {
		t.Fatal("reopen", err)
	}
	again, err := s.Put(raw)
	if err != nil || again != got {
		t.Fatal("repeat", err)
	}
	after, err := os.Stat(s.path(got))
	if err != nil || !os.SameFile(before, after) {
		t.Fatal("repeated put replaced inode", err)
	}
	names, err := os.ReadDir(dir)
	if err != nil || len(names) != 1 {
		t.Fatal("pending files after success", names, err)
	}
	// Opaque source objects, including empty bodies, retain their own byte hash.
	empty, err := s.Put(nil)
	if err != nil {
		t.Fatal(err)
	}
	if body, err := s.Get(empty); err != nil || len(body) != 0 {
		t.Fatal("empty body", err)
	}
}

func TestStoreConcurrentPublish(t *testing.T) {
	s, err := NewStore(t.TempDir(), 4096)
	if err != nil {
		t.Fatal(err)
	}
	raw := []byte("same object")
	var wg sync.WaitGroup
	errs := make(chan error, 20)
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); _, err := s.Put(raw); errs <- err }()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	entries, err := os.ReadDir(s.dir)
	if err != nil || len(entries) != 1 {
		t.Fatal("unexpected object count", err)
	}
}

func TestStoreTamperAndCollisionRefusal(t *testing.T) {
	s, err := NewStore(t.TempDir(), 20)
	if err != nil {
		t.Fatal(err)
	}
	raw := []byte("valid")
	h, err := s.Put(raw)
	if err != nil {
		t.Fatal(err)
	}
	path := s.path(h)
	if err = os.Chmod(path, 0600); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, []byte("alter"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Get(h); err == nil {
		t.Fatal("tamper accepted")
	}
	if _, err = s.Put(raw); err == nil {
		t.Fatal("corrupt object overwritten")
	}
	got, err := os.ReadFile(path)
	if err != nil || string(got) != "alter" {
		t.Fatal("corrupt file changed", err)
	}
}

func TestStoreLimitsAndUnsafeFiles(t *testing.T) {
	dir := t.TempDir()
	s, err := NewStore(dir, 4)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.Put([]byte("12345")); err == nil {
		t.Fatal("oversized put")
	}
	missing := protocol.Keccak256([]byte("missing"))
	if _, err = s.Get(missing); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("missing object", err)
	}
	body := []byte("12345")
	hash := protocol.Keccak256(body)
	if err = os.WriteFile(s.path(hash), body, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Get(hash); err == nil {
		t.Fatal("oversized read")
	}
	target := filepath.Join(t.TempDir(), "target")
	data := []byte("123")
	if err = os.WriteFile(target, data, 0600); err != nil {
		t.Fatal(err)
	}
	h := protocol.Keccak256(data)
	if err = os.Symlink(target, s.path(h)); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Get(h); err == nil {
		t.Fatal("symlink read")
	}
	if _, err = s.Put(data); err == nil {
		t.Fatal("symlink existing put")
	}
	directoryHash := protocol.Keccak256([]byte("dir"))
	if err = os.Mkdir(s.path(directoryHash), 0700); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Get(directoryHash); err == nil {
		t.Fatal("directory object read")
	}
	if _, err = NewStore(dir, 0); err == nil {
		t.Fatal("zero limit")
	}
	link := filepath.Join(t.TempDir(), "link")
	if err = os.Symlink(dir, link); err != nil {
		t.Fatal(err)
	}
	if _, err = NewStore(link, 4); err == nil {
		t.Fatal("symlink store")
	}
	if got := filepath.Base(s.path(hash)); got != fmt.Sprintf("%x", hash) || len(got) != 64 {
		t.Fatal("unsafe filename", got)
	}
}
