package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"time"
)

// serveHTTP exposes the same read API as scripts/inbox_server.py so the
// Python `inbox` source can point at either.
func serveHTTP(ctx context.Context, b *bridge, port int, token string) error {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "ok connected=%v\n", b.client.IsConnected())
	})
	mux.HandleFunc("GET /messages", func(w http.ResponseWriter, r *http.Request) {
		got := r.Header.Get("Authorization")
		if subtle.ConstantTimeCompare([]byte(got), []byte("Bearer "+token)) != 1 {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		var since time.Time
		if s := r.URL.Query().Get("since"); s != "" {
			t, err := time.Parse(time.RFC3339, s)
			if err != nil {
				http.Error(w, "bad since: "+err.Error(), http.StatusBadRequest)
				return
			}
			since = t
		}
		limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
		if limit <= 0 {
			limit = 300
		}
		msgs, err := b.store.query(since, r.URL.Query().Get("chat_id"), limit)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		if msgs == nil {
			msgs = []Record{}
		}
		w.Header().Set("Content-Type", "application/json")
		enc := json.NewEncoder(w)
		enc.SetEscapeHTML(false)
		_ = enc.Encode(map[string]any{"messages": msgs})
	})

	srv := &http.Server{Addr: fmt.Sprintf(":%d", port), Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutdownCtx)
	}()
	fmt.Fprintf(os.Stderr, "wa-bridge serving on :%d\n", port)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}
