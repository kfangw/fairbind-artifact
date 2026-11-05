// Package fsstore persists service state as one JSON document per record.
//
// Every write goes to a temporary file in the same directory, is fsynced,
// renamed over the target and followed by a directory fsync, so a reader
// after a crash sees either the old or the new document, never a torn one.
// A Store holds an exclusive advisory lock on its directory so two processes
// cannot share one data directory.
package fsstore

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
)

type Store struct {
	dir  string
	lock *os.File
}

// Open creates dir if needed and takes its lock.
func Open(dir string) (*Store, error) {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(filepath.Join(dir, ".lock"), os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		return nil, fmt.Errorf("data directory %s is in use: %w", dir, err)
	}
	return &Store{dir: dir, lock: f}, nil
}

// Close releases the directory lock.
func (s *Store) Close() error {
	syscall.Flock(int(s.lock.Fd()), syscall.LOCK_UN)
	return s.lock.Close()
}

// Dir returns the root directory.
func (s *Store) Dir() string { return s.dir }

func (s *Store) path(kind, id string) (string, error) {
	if kind == "" || id == "" || strings.ContainsAny(kind+id, "/\\") || strings.HasPrefix(id, ".") {
		return "", fmt.Errorf("invalid record name %q/%q", kind, id)
	}
	return filepath.Join(s.dir, kind, id+".json"), nil
}

// Put atomically replaces kind/id with the JSON encoding of v.
func (s *Store) Put(kind, id string, v any) error {
	p, err := s.path(kind, id)
	if err != nil {
		return err
	}
	data, err := json.MarshalIndent(v, "", " ")
	if err != nil {
		return err
	}
	return WriteFile(p, data)
}

// WriteFile writes data to path atomically and durably.
func WriteFile(path string, data []byte) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	f, err := os.CreateTemp(dir, ".tmp-*")
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
	d, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}

// Get decodes kind/id into v. It returns false when the record is absent.
func (s *Store) Get(kind, id string, v any) (bool, error) {
	p, err := s.path(kind, id)
	if err != nil {
		return false, err
	}
	data, err := os.ReadFile(p)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if err = dec.Decode(v); err != nil {
		return false, fmt.Errorf("%s: %w", p, err)
	}
	return true, nil
}

// Delete removes kind/id if present.
func (s *Store) Delete(kind, id string) error {
	p, err := s.path(kind, id)
	if err != nil {
		return err
	}
	if err = os.Remove(p); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

// List returns the record ids of kind in lexical order.
func (s *Store) List(kind string) ([]string, error) {
	entries, err := os.ReadDir(filepath.Join(s.dir, kind))
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var ids []string
	for _, e := range entries {
		name := e.Name()
		if e.Type().IsRegular() && strings.HasSuffix(name, ".json") && !strings.HasPrefix(name, ".") {
			ids = append(ids, strings.TrimSuffix(name, ".json"))
		}
	}
	sort.Strings(ids)
	return ids, nil
}
