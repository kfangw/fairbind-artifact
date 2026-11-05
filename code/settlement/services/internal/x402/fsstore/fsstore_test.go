package fsstore

import (
	"os"
	"path/filepath"
	"testing"
)

type rec struct {
	A int    `json:"a"`
	B string `json:"b"`
}

func TestPutGetListDelete(t *testing.T) {
	dir := t.TempDir()
	s, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Open(dir); err == nil {
		t.Fatal("second open of a locked directory succeeded")
	}
	if err = s.Put("k", "x", rec{1, "one"}); err != nil {
		t.Fatal(err)
	}
	if err = s.Put("k", "a", rec{2, "two"}); err != nil {
		t.Fatal(err)
	}
	var r rec
	if ok, err := s.Get("k", "x", &r); !ok || err != nil || r.A != 1 {
		t.Fatalf("get: %v %v %+v", ok, err, r)
	}
	ids, _ := s.List("k")
	if len(ids) != 2 || ids[0] != "a" {
		t.Fatalf("list %v", ids)
	}
	os.WriteFile(filepath.Join(dir, "k", "bad.json"), []byte(`{"a":1,"zzz":2}`), 0o600)
	if _, err := s.Get("k", "bad", &r); err == nil {
		t.Fatal("unknown field accepted")
	}
	if ok, _ := s.Get("k", "missing", &r); ok {
		t.Fatal("missing record found")
	}
	if _, err := s.Get("../x", "y", &r); err == nil {
		t.Fatal("path traversal accepted")
	}
	s.Delete("k", "x")
	if ok, _ := s.Get("k", "x", &r); ok {
		t.Fatal("deleted record found")
	}
	s.Close()
	s2, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	s2.Close()
}
