package main

import (
	"database/sql"
	"encoding/json"
	"time"
)

// Record is the JSON contract shared with the Python side (see
// wacal/model.py normalise_message and scripts/inbox_server.py).
type Record struct {
	ID        string  `json:"id"`
	ChatID    string  `json:"chat_id"`
	ChatName  string  `json:"chat_name,omitempty"`
	Sender    string  `json:"sender"`
	Timestamp string  `json:"timestamp"` // RFC3339 UTC
	Text      string  `json:"text"`
	ReplyTo   *string `json:"reply_to"`
	MediaType *string `json:"media_type"`
	FromMe    bool    `json:"from_me"`
	Raw       any     `json:"-"`
}

const schema = `
CREATE TABLE IF NOT EXISTS messages (
  id          TEXT PRIMARY KEY,
  chat_id     TEXT NOT NULL,
  sender      TEXT NOT NULL,
  ts          TEXT NOT NULL,
  text        TEXT NOT NULL,
  reply_to    TEXT,
  media_type  TEXT,
  from_me     INTEGER NOT NULL DEFAULT 0,
  raw         TEXT NOT NULL,
  received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_ts ON messages(ts);
CREATE INDEX IF NOT EXISTS messages_chat_ts ON messages(chat_id, ts);
CREATE TABLE IF NOT EXISTS chat_names (
  chat_id TEXT PRIMARY KEY,
  name    TEXT NOT NULL
);
`

type messageStore struct {
	db *sql.DB
}

func openMessageStore(path string) (*messageStore, error) {
	db, err := sql.Open("sqlite3", "file:"+path+"?_journal_mode=WAL&_busy_timeout=5000")
	if err != nil {
		return nil, err
	}
	if _, err := db.Exec(schema); err != nil {
		db.Close()
		return nil, err
	}
	return &messageStore{db: db}, nil
}

func (s *messageStore) Close() { s.db.Close() }

// upsert inserts a message, or replaces its text/raw when the same id arrives
// again (edits carry the original id).
func (s *messageStore) upsert(r Record) error {
	raw, _ := json.Marshal(r.Raw)
	_, err := s.db.Exec(`
INSERT INTO messages (id, chat_id, sender, ts, text, reply_to, media_type, from_me, raw, received_at)
VALUES (?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(id) DO UPDATE SET text = excluded.text, raw = excluded.raw, media_type = excluded.media_type`,
		r.ID, r.ChatID, r.Sender, r.Timestamp, r.Text, r.ReplyTo, r.MediaType, r.FromMe, string(raw),
		time.Now().UTC().Format(time.RFC3339))
	return err
}

func (s *messageStore) setChatName(chatID, name string) error {
	_, err := s.db.Exec(`INSERT INTO chat_names (chat_id, name) VALUES (?, ?)
ON CONFLICT(chat_id) DO UPDATE SET name = excluded.name`, chatID, name)
	return err
}

func (s *messageStore) count() int {
	var n int
	_ = s.db.QueryRow(`SELECT COUNT(*) FROM messages`).Scan(&n)
	return n
}

// query returns messages newer than since (zero = all), optionally for one
// chat, oldest first.
func (s *messageStore) query(since time.Time, chatID string, limit int) ([]Record, error) {
	if limit <= 0 || limit > 5000 {
		limit = 5000
	}
	q := `SELECT m.id, m.chat_id, COALESCE(c.name, ''), m.sender, m.ts, m.text, m.reply_to, m.media_type, m.from_me
	      FROM messages m LEFT JOIN chat_names c ON c.chat_id = m.chat_id WHERE 1=1`
	args := []any{}
	if !since.IsZero() {
		q += ` AND m.ts > ?`
		args = append(args, since.UTC().Format(time.RFC3339))
	}
	if chatID != "" {
		q += ` AND m.chat_id = ?`
		args = append(args, chatID)
	}
	q += ` ORDER BY m.ts ASC, m.id ASC LIMIT ?`
	args = append(args, limit)

	rows, err := s.db.Query(q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Record
	for rows.Next() {
		var r Record
		var fromMe int
		if err := rows.Scan(&r.ID, &r.ChatID, &r.ChatName, &r.Sender, &r.Timestamp, &r.Text, &r.ReplyTo, &r.MediaType, &fromMe); err != nil {
			return nil, err
		}
		r.FromMe = fromMe != 0
		out = append(out, r)
	}
	return out, rows.Err()
}
