package directive

import (
	"fmt"
	"os"
	"path/filepath"
)

// WriteProgress records the block a completed pass of a service started from,
// atomically (temporary file and rename). A harness that advances the chain
// waits until every service has reported the current head before it mines
// further, so a call due at that head is included in the next block. An empty
// path writes nothing.
func WriteProgress(path string, head uint64) error {
	if path == "" {
		return nil
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".progress-")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if _, err = fmt.Fprintf(f, "{\"head\":%d}\n", head); err != nil {
		f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	return os.Rename(name, path)
}
