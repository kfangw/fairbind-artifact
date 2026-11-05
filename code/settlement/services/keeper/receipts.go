package keeper

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
)

// DirReceiptList reads the published receipt list (A-LEAF) from a directory
// holding one JSON file per purchase, named by its nonce in lower-case hex
// with the 0x prefix: {"receipt": <receipt with signature>, "receiptProof":
// <inclusion proof>}, the shapes of the serve bundle schema. A missing file
// means the receipt is not published.
type DirReceiptList struct {
	Dir string
}

type publishedReceipt struct {
	Receipt      x402.Receipt `json:"receipt"`
	ReceiptProof x402.Proof   `json:"receiptProof"`
}

func (l DirReceiptList) SampleReceipt(_ context.Context, nonce protocol.Bytes32) (SignedReceipt, bool, error) {
	raw, err := os.ReadFile(filepath.Join(l.Dir, hexKey(nonce)+".json"))
	if errors.Is(err, os.ErrNotExist) {
		return SignedReceipt{}, false, nil
	}
	if err != nil {
		return SignedReceipt{}, false, err
	}
	var p publishedReceipt
	if err := json.Unmarshal(raw, &p); err != nil {
		return SignedReceipt{}, false, fmt.Errorf("receipt %s: %w", hexKey(nonce), err)
	}
	sig, err := p.Receipt.SignatureBytes()
	if err != nil {
		return SignedReceipt{}, false, fmt.Errorf("receipt %s: %w", hexKey(nonce), err)
	}
	r := SignedReceipt{Receipt: p.Receipt.Typed(), Signature: sig, Proof: p.ReceiptProof.Typed()}
	if r.Receipt.Nonce != nonce {
		return SignedReceipt{}, false, fmt.Errorf("receipt %s names another purchase", hexKey(nonce))
	}
	return r, true, nil
}
