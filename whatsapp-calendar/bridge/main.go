// wa-bridge links to WhatsApp as a companion device (WhatsApp Web multidevice
// protocol, via go.mau.fi/whatsmeow), stores incoming messages in SQLite and
// hands them to the Python side of wacal in the same JSON shape as
// scripts/inbox_server.py.
//
//	wa-bridge link [--phone +447700900123]   pair once (QR or pairing code)
//	wa-bridge fetch [--since ISO] [--limit N] [--chat JID] [--wait 20s]
//	                                          one-shot: connect, drain queued
//	                                          messages, print JSON, exit
//	wa-bridge serve [--port 8080]             daemon with GET /messages API
//	wa-bridge groups                          list group JIDs and names
//
// Settings (env, or .env in the wacal project root):
//
//	WACAL_WA_SESSION_DB   whatsmeow session + keys (default state/whatsmeow.db)
//	WACAL_WA_MESSAGES_DB  stored messages          (default state/wa-messages.sqlite3)
//	WACAL_WA_CHATS        comma-separated chat JIDs to keep; empty = every chat
//	WACAL_INBOX_TOKEN     bearer token for `serve`
//	TIMEZONE              used only to render WhatsApp Event message times
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	_ "github.com/mattn/go-sqlite3"
	"github.com/mdp/qrterminal/v3"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	loadDotenv()
	var err error
	switch os.Args[1] {
	case "link":
		err = cmdLink(os.Args[2:])
	case "fetch":
		err = cmdFetch(os.Args[2:])
	case "serve":
		err = cmdServe(os.Args[2:])
	case "groups":
		err = cmdGroups(os.Args[2:])
	case "-h", "--help", "help":
		usage()
	default:
		usage()
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprint(os.Stderr, `usage: wa-bridge <link|fetch|serve|groups> [flags]

  link    pair this bridge with your phone (QR in terminal, or --phone for a pairing code)
  fetch   connect, drain queued messages, print them as JSON, disconnect
  serve   stay connected and expose GET /messages (same API as inbox_server.py)
  groups  print the JIDs and names of your groups (for WACAL_WA_CHATS / --chat)

Run "wa-bridge <command> -h" for flags.
`)
}

// ---------------------------------------------------------------------------
// shared wiring
// ---------------------------------------------------------------------------

type bridge struct {
	client *whatsmeow.Client
	store  *messageStore
	keep   map[string]bool // chat JIDs to keep; empty = all
	log    *stderrLogger
}

func projectRoot() string {
	if v := os.Getenv("WACAL_PROJECT_ROOT"); v != "" {
		return v
	}
	exe, err := os.Executable()
	if err == nil {
		// bridge/wa-bridge -> project root is the parent of bridge/
		if _, statErr := os.Stat(filepath.Join(filepath.Dir(exe), "..", "wacal")); statErr == nil {
			return filepath.Clean(filepath.Join(filepath.Dir(exe), ".."))
		}
	}
	cwd, _ := os.Getwd()
	if _, statErr := os.Stat(filepath.Join(cwd, "..", "wacal")); statErr == nil {
		return filepath.Clean(filepath.Join(cwd, ".."))
	}
	return cwd
}

func stateDir() string {
	if v := os.Getenv("WACAL_STATE_DIR"); v != "" {
		return v
	}
	return filepath.Join(projectRoot(), "state")
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// loadDotenv mirrors wacal/config.py: env wins, .env fills gaps.
func loadDotenv() {
	data, err := os.ReadFile(filepath.Join(projectRoot(), ".env"))
	if err != nil {
		return
	}
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
			continue
		}
		k, v, _ := strings.Cut(line, "=")
		k = strings.TrimSpace(k)
		v = strings.TrimSpace(v)
		if i := strings.Index(v, " #"); i >= 0 { // trailing comment
			v = strings.TrimSpace(v[:i])
		}
		v = strings.Trim(v, `"'`)
		if os.Getenv(k) == "" {
			os.Setenv(k, v)
		}
	}
}

func newBridge(ctx context.Context) (*bridge, error) {
	if err := os.MkdirAll(stateDir(), 0o700); err != nil {
		return nil, err
	}
	sessionDB := envOr("WACAL_WA_SESSION_DB", filepath.Join(stateDir(), "whatsmeow.db"))
	messagesDB := envOr("WACAL_WA_MESSAGES_DB", filepath.Join(stateDir(), "wa-messages.sqlite3"))
	log := &stderrLogger{module: "wa-bridge", level: envOr("WACAL_WA_LOG_LEVEL", "WARN")}

	container, err := sqlstore.New(ctx, "sqlite3", "file:"+sessionDB+"?_foreign_keys=on", log.Sub("DB"))
	if err != nil {
		return nil, fmt.Errorf("open session db: %w", err)
	}
	device, err := container.GetFirstDevice(ctx)
	if err != nil {
		return nil, fmt.Errorf("get device: %w", err)
	}
	client := whatsmeow.NewClient(device, log.Sub("Client"))

	store, err := openMessageStore(messagesDB)
	if err != nil {
		return nil, fmt.Errorf("open messages db: %w", err)
	}

	b := &bridge{client: client, store: store, keep: map[string]bool{}, log: log}
	for _, jid := range strings.Split(envOr("WACAL_WA_CHATS", ""), ",") {
		if jid = strings.TrimSpace(jid); jid != "" {
			b.keep[jid] = true
		}
	}
	return b, nil
}

func (b *bridge) close() {
	b.client.Disconnect()
	b.store.Close()
}

func (b *bridge) wantsChat(chat types.JID) bool {
	return len(b.keep) == 0 || b.keep[chat.String()]
}

// handle is the whatsmeow event handler. It stores anything that looks like a
// message and signals sync milestones on the given channels.
func (b *bridge) handle(offlineDone chan<- int, historyDone chan<- struct{}) func(any) {
	return func(raw any) {
		switch evt := raw.(type) {
		case *events.Message:
			b.storeEvent(evt)
		case *events.HistorySync:
			n := 0
			for _, conv := range evt.Data.GetConversations() {
				chat, err := types.ParseJID(conv.GetID())
				if err != nil {
					continue
				}
				if name := conv.GetName(); name != "" {
					_ = b.store.setChatName(chat.String(), name)
				}
				for _, hm := range conv.GetMessages() {
					msg, err := b.client.ParseWebMessage(chat, hm.GetMessage())
					if err != nil {
						continue
					}
					if b.storeEvent(msg) {
						n++
					}
				}
			}
			b.log.Infof("history sync (%s, progress %d%%): stored %d messages",
				evt.Data.GetSyncType(), evt.Data.GetProgress(), n)
			if evt.Data.GetProgress() >= 100 && historyDone != nil {
				select {
				case historyDone <- struct{}{}:
				default:
				}
			}
		case *events.OfflineSyncCompleted:
			b.log.Infof("offline sync completed: %d events", evt.Count)
			if offlineDone != nil {
				select {
				case offlineDone <- evt.Count:
				default:
				}
			}
		case *events.LoggedOut:
			b.log.Errorf("logged out (reason %v). Delete %s and run `wa-bridge link` again.",
				evt.Reason, envOr("WACAL_WA_SESSION_DB", filepath.Join(stateDir(), "whatsmeow.db")))
		case *events.Connected:
			b.log.Infof("connected as %s", b.client.Store.ID)
			go b.refreshGroupNames()
		}
	}
}

func (b *bridge) storeEvent(evt *events.Message) bool {
	if !b.wantsChat(evt.Info.Chat) {
		return false
	}
	rec, ok := convert(evt)
	if !ok {
		return false
	}
	if err := b.store.upsert(rec); err != nil {
		b.log.Warnf("store %s: %v", rec.ID, err)
		return false
	}
	return true
}

func (b *bridge) refreshGroupNames() {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	groups, err := b.client.GetJoinedGroups(ctx)
	if err != nil {
		b.log.Warnf("list groups: %v", err)
		return
	}
	for _, g := range groups {
		_ = b.store.setChatName(g.JID.String(), g.Name)
	}
}

func (b *bridge) mustBeLinked() error {
	if b.client.Store.ID == nil {
		return errors.New("not linked to a phone yet; run `wa-bridge link` first")
	}
	return nil
}

func signalContext() (context.Context, context.CancelFunc) {
	return signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
}

// ---------------------------------------------------------------------------
// link
// ---------------------------------------------------------------------------

func cmdLink(args []string) error {
	fs := flag.NewFlagSet("link", flag.ExitOnError)
	phone := fs.String("phone", "", "pair with a code instead of a QR: your number in E.164, e.g. +447700900123")
	wait := fs.Duration("wait", 90*time.Second, "after pairing, wait this long for the initial history sync")
	_ = fs.Parse(args)

	ctx, cancel := signalContext()
	defer cancel()
	b, err := newBridge(ctx)
	if err != nil {
		return err
	}
	defer b.close()

	if b.client.Store.ID != nil {
		fmt.Fprintf(os.Stderr, "already linked as %s; delete the session db to re-link\n", b.client.Store.ID)
		return nil
	}

	historyDone := make(chan struct{}, 1)
	b.client.AddEventHandler(b.handle(nil, historyDone))

	qrChan, err := b.client.GetQRChannel(ctx)
	if err != nil {
		return err
	}
	if err := b.client.Connect(); err != nil {
		return err
	}
	if *phone != "" {
		code, err := b.client.PairPhone(ctx, strings.TrimPrefix(*phone, "+"), true, whatsmeow.PairClientChrome, "wacal bridge")
		if err != nil {
			return fmt.Errorf("request pairing code: %w", err)
		}
		fmt.Fprintf(os.Stderr, "\nOn your phone: WhatsApp > Linked devices > Link a device > Link with phone number\nEnter this code: %s\n\n", code)
	} else {
		fmt.Fprintln(os.Stderr, "\nOn your phone: WhatsApp > Linked devices > Link a device, then scan:")
	}

	for item := range qrChan {
		switch item.Event {
		case "code":
			if *phone == "" {
				qrterminal.GenerateHalfBlock(item.Code, qrterminal.L, os.Stderr)
				fmt.Fprintf(os.Stderr, "(new code every %s)\n", item.Timeout)
			}
		case "success":
			fmt.Fprintf(os.Stderr, "paired as %s\n", b.client.Store.ID)
			goto paired
		case "timeout":
			return errors.New("pairing timed out; run link again")
		case "error":
			return fmt.Errorf("pairing failed: %w", item.Error)
		default:
			fmt.Fprintln(os.Stderr, "pairing:", item.Event)
		}
	}
paired:
	fmt.Fprintf(os.Stderr, "waiting up to %s for the initial history sync...\n", *wait)
	select {
	case <-historyDone:
		fmt.Fprintln(os.Stderr, "history sync complete")
	case <-time.After(*wait):
		fmt.Fprintln(os.Stderr, "stopped waiting; more history may arrive on the next fetch/serve")
	case <-ctx.Done():
	}
	fmt.Fprintf(os.Stderr, "stored %d messages so far. Next: `wa-bridge groups` to find chat JIDs.\n", b.store.count())
	return nil
}

// ---------------------------------------------------------------------------
// fetch (one-shot)
// ---------------------------------------------------------------------------

func cmdFetch(args []string) error {
	fs := flag.NewFlagSet("fetch", flag.ExitOnError)
	since := fs.String("since", "", "only messages after this RFC3339 timestamp")
	limit := fs.Int("limit", 300, "maximum messages to print")
	chat := fs.String("chat", "", "only this chat JID")
	wait := fs.Duration("wait", 20*time.Second, "max time to wait for queued messages to arrive")
	offline := fs.Bool("offline", false, "do not connect; just print what is already stored")
	_ = fs.Parse(args)

	var sinceT time.Time
	if *since != "" {
		t, err := time.Parse(time.RFC3339, *since)
		if err != nil {
			return fmt.Errorf("--since: %w", err)
		}
		sinceT = t
	}

	ctx, cancel := signalContext()
	defer cancel()
	b, err := newBridge(ctx)
	if err != nil {
		return err
	}
	defer b.close()

	if !*offline {
		if err := b.mustBeLinked(); err != nil {
			return err
		}
		offlineDone := make(chan int, 1)
		b.client.AddEventHandler(b.handle(offlineDone, nil))
		if err := b.client.Connect(); err != nil {
			return err
		}
		select {
		case <-offlineDone:
			// Give any decrypt retries a moment to land.
			time.Sleep(2 * time.Second)
		case <-time.After(*wait):
			b.log.Warnf("no offline-sync-complete within %s; printing what we have", *wait)
		case <-ctx.Done():
			return ctx.Err()
		}
	}

	msgs, err := b.store.query(sinceT, *chat, *limit)
	if err != nil {
		return err
	}
	if msgs == nil {
		msgs = []Record{}
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	return enc.Encode(map[string]any{"messages": msgs})
}

// ---------------------------------------------------------------------------
// serve (daemon)
// ---------------------------------------------------------------------------

func cmdServe(args []string) error {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)
	port := fs.Int("port", atoiOr(os.Getenv("PORT"), 8080), "HTTP port")
	_ = fs.Parse(args)

	token := os.Getenv("WACAL_INBOX_TOKEN")
	if token == "" {
		return errors.New("WACAL_INBOX_TOKEN must be set for serve")
	}

	ctx, cancel := signalContext()
	defer cancel()
	b, err := newBridge(ctx)
	if err != nil {
		return err
	}
	defer b.close()
	if err := b.mustBeLinked(); err != nil {
		return err
	}
	b.client.AddEventHandler(b.handle(nil, nil))
	if err := b.client.Connect(); err != nil {
		return err
	}
	return serveHTTP(ctx, b, *port, token)
}

// ---------------------------------------------------------------------------
// groups
// ---------------------------------------------------------------------------

func cmdGroups(args []string) error {
	fs := flag.NewFlagSet("groups", flag.ExitOnError)
	_ = fs.Parse(args)

	ctx, cancel := signalContext()
	defer cancel()
	b, err := newBridge(ctx)
	if err != nil {
		return err
	}
	defer b.close()
	if err := b.mustBeLinked(); err != nil {
		return err
	}
	if err := b.client.Connect(); err != nil {
		return err
	}
	// Wait for the connection to be usable.
	deadline := time.Now().Add(15 * time.Second)
	for !b.client.IsConnected() && time.Now().Before(deadline) {
		time.Sleep(200 * time.Millisecond)
	}
	groups, err := b.client.GetJoinedGroups(ctx)
	if err != nil {
		return err
	}
	type row struct {
		JID          string `json:"jid"`
		Name         string `json:"name"`
		Participants int    `json:"participants"`
	}
	out := make([]row, 0, len(groups))
	for _, g := range groups {
		_ = b.store.setChatName(g.JID.String(), g.Name)
		out = append(out, row{g.JID.String(), g.Name, len(g.Participants)})
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(map[string]any{"groups": out})
}

func atoiOr(s string, def int) int {
	var n int
	if _, err := fmt.Sscanf(s, "%d", &n); err != nil {
		return def
	}
	return n
}
