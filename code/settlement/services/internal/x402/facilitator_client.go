package x402

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// FacilitatorClient submits a payment to a facilitator's /settle endpoint.
// A returned response may have Success false; an error means the outcome is
// unknown.
type FacilitatorClient interface {
	Settle(ctx context.Context, req SettleRequest) (SettlementResponse, error)
}

// HTTPFacilitator is a FacilitatorClient over HTTP.
type HTTPFacilitator struct {
	URL    string
	Client *http.Client
}

func (h HTTPFacilitator) Settle(ctx context.Context, req SettleRequest) (SettlementResponse, error) {
	var out SettlementResponse
	body, err := json.Marshal(req)
	if err != nil {
		return out, err
	}
	r, err := http.NewRequestWithContext(ctx, http.MethodPost, h.URL+"/settle", bytes.NewReader(body))
	if err != nil {
		return out, err
	}
	r.Header.Set("Content-Type", "application/json")
	c := h.Client
	if c == nil {
		c = &http.Client{Timeout: 90 * time.Second}
	}
	resp, err := c.Do(r)
	if err != nil {
		return out, err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return out, err
	}
	if resp.StatusCode >= 500 {
		return out, fmt.Errorf("facilitator status %d: %s", resp.StatusCode, bytes.TrimSpace(raw))
	}
	if err = json.Unmarshal(raw, &out); err != nil {
		return out, fmt.Errorf("facilitator response: %w", err)
	}
	if !out.Success && out.ErrorReason == "" {
		out.ErrorReason = fmt.Sprintf("facilitator_status_%d", resp.StatusCode)
	}
	return out, nil
}
