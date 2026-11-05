package evidence

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"syscall"

	"example.org/fairbind/protocol"
)

// Store uses an operator-owned local directory. It must not be replaced or
// modified by another OS principal. Stored objects are immutable through this
// API; Get detects later content corruption. No retention deletion is provided.
// Filesystem atomic hard links and directory fsync are required (local Unix).
type Store struct {
	dir      string
	maxBytes int64
}

func syncDir(dir string) error {
	f, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer f.Close()
	return f.Sync()
}

// NewStore creates at most one directory under an existing parent so successful
// parent fsync also makes its creation durable. It does not create ancestor trees.
func NewStore(dir string, maxBytes int64) (*Store, error) {
	if maxBytes <= 0 || maxBytes == math.MaxInt64 {
		return nil, fmt.Errorf("invalid object size limit")
	}
	dir, err := filepath.Abs(dir)
	if err != nil {
		return nil, err
	}
	if err = os.Mkdir(dir, 0700); err != nil && !errors.Is(err, os.ErrExist) {
		return nil, err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return nil, err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, fmt.Errorf("store must be a real directory")
	}
	if err = syncDir(dir); err != nil {
		return nil, err
	}
	if err = syncDir(filepath.Dir(dir)); err != nil {
		return nil, err
	}
	return &Store{dir: dir, maxBytes: maxBytes}, nil
}

func (s *Store) path(hash protocol.Bytes32) string {
	return filepath.Join(s.dir, fmt.Sprintf("%x", hash))
}

// Put durably publishes exact bytes without replacing an existing object. The
// digest has a fixed-width binary type, so callers cannot inject a path. A retry
// verifies an existing object's bytes and fsyncs the directory before success.
// If fsync fails after publication, an error is returned and retry is safe.
func (s *Store) Put(raw []byte) (protocol.Bytes32, error) {
	var zero protocol.Bytes32
	if s == nil || s.maxBytes <= 0 || int64(len(raw)) > s.maxBytes {
		return zero, fmt.Errorf("object exceeds store limit or uninitialized store")
	}
	hash := protocol.Keccak256(raw)
	f, err := os.CreateTemp(s.dir, ".pending-")
	if err != nil {
		return zero, err
	}
	tmp := f.Name()
	defer os.Remove(tmp)
	defer f.Close()
	if _, err = f.Write(raw); err != nil {
		return zero, err
	}
	if err = f.Chmod(0444); err != nil {
		return zero, err
	}
	if err = f.Sync(); err != nil {
		return zero, err
	}
	if err = f.Close(); err != nil {
		return zero, err
	}
	if err = os.Link(tmp, s.path(hash)); err != nil {
		if !errors.Is(err, os.ErrExist) {
			return zero, err
		}
		existing, getErr := s.Get(hash)
		if getErr != nil {
			return zero, getErr
		}
		if !bytes.Equal(existing, raw) {
			return zero, fmt.Errorf("existing object differs")
		}
	}
	if err = os.Remove(tmp); err != nil {
		return zero, err
	}
	if err = syncDir(s.dir); err != nil {
		return zero, err
	}
	return hash, nil
}

// Get refuses symlinks and nonregular files, enforces the configured byte limit,
// and recomputes the digest before returning data. Missing is os.ErrNotExist.
func (s *Store) Get(hash protocol.Bytes32) ([]byte, error) {
	if s == nil || s.maxBytes <= 0 {
		return nil, fmt.Errorf("uninitialized store")
	}
	f, err := os.OpenFile(s.path(hash), os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > s.maxBytes {
		return nil, fmt.Errorf("invalid object file or size")
	}
	raw, err := io.ReadAll(io.LimitReader(f, s.maxBytes+1))
	if err != nil {
		return nil, err
	}
	if int64(len(raw)) > s.maxBytes {
		return nil, fmt.Errorf("object exceeds store limit")
	}
	if protocol.Keccak256(raw) != hash {
		return nil, fmt.Errorf("object digest mismatch")
	}
	return raw, nil
}
