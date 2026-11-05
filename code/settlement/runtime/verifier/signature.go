package verifier

import (
	"bytes"
	"context"
	"encoding/hex"
	"fmt"
	"os/exec"
	"strings"
	"time"

	"example.org/fairbind/protocol"
)

const CastCommit = "4072e48705af9d93e3c0f6e29e93b5e9a40caed8"

// CastVerifier's executable path is trusted deployment configuration, never
// selected by bundle input. Both version and positive recovery output are checked.
type CastVerifier struct{ Path string }

func (v CastVerifier) Verify(ctx context.Context, key protocol.Address, digest protocol.Bytes32, sig []byte) error {
	if len(sig) != 65 || (sig[64] != 27 && sig[64] != 28) {
		return fmt.Errorf("noncanonical signature")
	}
	half, _ := hex.DecodeString("7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0")
	if bytes.Equal(sig[:32], make([]byte, 32)) || bytes.Equal(sig[32:64], make([]byte, 32)) || bytes.Compare(sig[32:64], half) > 0 {
		return fmt.Errorf("noncanonical signature")
	}
	path := v.Path
	if path == "" {
		path = "cast"
	}
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	version, e := exec.CommandContext(ctx, path, "--version").CombinedOutput()
	if e != nil || !strings.Contains(string(version), "cast Version: 1.7.1\n") || !strings.Contains(string(version), "Commit SHA: "+CastCommit+"\n") {
		return fmt.Errorf("unsupported cast build")
	}
	out, e := exec.CommandContext(ctx, path, "wallet", "verify", "--no-hash", "--color", "never", "--address", "0x"+hex.EncodeToString(key[:]), "0x"+hex.EncodeToString(digest[:]), "0x"+hex.EncodeToString(sig)).CombinedOutput()
	if e != nil || !strings.Contains(strings.ToLower(string(out)), "validation succeeded. address 0x"+hex.EncodeToString(key[:])+" signed this message.") {
		return fmt.Errorf("signature recovery failed")
	}
	return nil
}
