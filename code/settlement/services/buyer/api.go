package buyer

import (
	"encoding/json"
	"io"
	"net/http"
)

// Handler returns the local control API:
//
//	POST /purchases       body: Request JSON; runs a new purchase
//	GET  /purchases       list of purchase ids
//	GET  /purchases/{id}  one purchase record
//	POST /purchases/{id}/advance  run the next steps now
//
// It has no authentication and must listen on a loopback address.
func (b *Buyer) Handler() http.Handler {
	mux := http.NewServeMux()
	write := func(w http.ResponseWriter, status int, v any) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		json.NewEncoder(w).Encode(v)
	}
	mux.HandleFunc("POST /purchases", func(w http.ResponseWriter, r *http.Request) {
		var req Request
		raw, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
		if err == nil {
			err = json.Unmarshal(raw, &req)
		}
		if err != nil || req.URL == "" {
			write(w, http.StatusBadRequest, map[string]string{"error": "invalid request"})
			return
		}
		rec, err := b.Buy(r.Context(), req)
		if rec == nil {
			write(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		write(w, http.StatusOK, rec)
	})
	mux.HandleFunc("GET /purchases", func(w http.ResponseWriter, r *http.Request) {
		ids, err := b.List()
		if err != nil {
			write(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		if ids == nil {
			ids = []string{}
		}
		write(w, http.StatusOK, ids)
	})
	mux.HandleFunc("GET /purchases/{id}", func(w http.ResponseWriter, r *http.Request) {
		rec, err := b.Get(r.PathValue("id"))
		if err != nil {
			write(w, http.StatusNotFound, map[string]string{"error": err.Error()})
			return
		}
		write(w, http.StatusOK, rec)
	})
	mux.HandleFunc("POST /purchases/{id}/advance", func(w http.ResponseWriter, r *http.Request) {
		rec, err := b.Advance(r.Context(), r.PathValue("id"))
		if rec == nil {
			write(w, http.StatusNotFound, map[string]string{"error": err.Error()})
			return
		}
		write(w, http.StatusOK, rec)
	})
	return mux
}
