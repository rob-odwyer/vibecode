package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"go.mau.fi/whatsmeow/proto/waCommon"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	"google.golang.org/protobuf/proto"
)

var (
	group = types.NewJID("120363000000000000", types.GroupServer)
	alice = types.NewJID("447700900123", types.DefaultUserServer)
	when  = time.Date(2026, 9, 28, 13, 5, 0, 0, time.UTC)
)

func evt(id string, m *waE2E.Message) *events.Message {
	return &events.Message{
		Info: types.MessageInfo{
			MessageSource: types.MessageSource{Chat: group, Sender: alice, IsGroup: true},
			ID:            types.MessageID(id),
			PushName:      "Alice",
			Timestamp:     when,
		},
		Message: m,
	}
}

func TestConvertPlainText(t *testing.T) {
	r, ok := convert(evt("A1", &waE2E.Message{Conversation: proto.String("Dentist Thursday 4pm")}))
	if !ok {
		t.Fatal("expected ok")
	}
	if r.ID != "A1" || r.ChatID != group.String() || r.Sender != "Alice" || r.Text != "Dentist Thursday 4pm" {
		t.Fatalf("bad record: %+v", r)
	}
	if r.Timestamp != "2026-09-28T13:05:00Z" {
		t.Fatalf("timestamp %q", r.Timestamp)
	}
	if r.ReplyTo != nil || r.MediaType != nil {
		t.Fatalf("unexpected reply/media: %+v", r)
	}
}

func TestConvertReplyAndCaption(t *testing.T) {
	m := &waE2E.Message{ImageMessage: &waE2E.ImageMessage{
		Caption:     proto.String("the invite"),
		ContextInfo: &waE2E.ContextInfo{StanzaID: proto.String("A1")},
	}}
	r, ok := convert(evt("A2", m))
	if !ok || r.Text != "the invite" || *r.MediaType != "image" || *r.ReplyTo != "A1" {
		t.Fatalf("bad record: %+v ok=%v", r, ok)
	}
}

func TestConvertFromMe(t *testing.T) {
	e := evt("A3", &waE2E.Message{Conversation: proto.String("ok")})
	e.Info.IsFromMe = true
	r, _ := convert(e)
	if r.Sender != "me" || !r.FromMe {
		t.Fatalf("bad record: %+v", r)
	}
}

func TestConvertSkipsReactions(t *testing.T) {
	if _, ok := convert(evt("A4", &waE2E.Message{ReactionMessage: &waE2E.ReactionMessage{Text: proto.String("👍")}})); ok {
		t.Fatal("reactions should be skipped")
	}
	if _, ok := convert(evt("A5", &waE2E.Message{ProtocolMessage: &waE2E.ProtocolMessage{Type: waE2E.ProtocolMessage_REVOKE.Enum()}})); ok {
		t.Fatal("revokes should be skipped")
	}
}

func TestConvertEditKeepsOriginalID(t *testing.T) {
	m := &waE2E.Message{ProtocolMessage: &waE2E.ProtocolMessage{
		Type:          waE2E.ProtocolMessage_MESSAGE_EDIT.Enum(),
		Key:           &waCommon.MessageKey{ID: proto.String("A1")},
		EditedMessage: &waE2E.Message{Conversation: proto.String("Dentist Friday 4pm")},
	}}
	r, ok := convert(evt("EDIT9", m))
	if !ok || r.ID != "A1" || r.Text != "Dentist Friday 4pm" {
		t.Fatalf("bad record: %+v ok=%v", r, ok)
	}
}

func TestConvertNativeEvent(t *testing.T) {
	os.Setenv("TIMEZONE", "Europe/London")
	start := time.Date(2026, 10, 8, 15, 0, 0, 0, time.UTC).Unix() // 16:00 BST
	m := &waE2E.Message{EventMessage: &waE2E.EventMessage{
		Name:        proto.String("Sam's birthday party"),
		StartTime:   proto.Int64(start),
		Location:    &waE2E.LocationMessage{Name: proto.String("Soft play"), Address: proto.String("High St")},
		Description: proto.String("bring a present"),
	}}
	r, ok := convert(evt("E1", m))
	if !ok || *r.MediaType != "event" {
		t.Fatalf("bad record: %+v ok=%v", r, ok)
	}
	want := "[event] Sam's birthday party\nstart: 2026-10-08T16:00:00+01:00\nlocation: Soft play High St\nbring a present"
	if r.Text != want {
		t.Fatalf("got:\n%s\nwant:\n%s", r.Text, want)
	}
}

func TestStoreRoundTripAndEdit(t *testing.T) {
	s, err := openMessageStore(filepath.Join(t.TempDir(), "m.sqlite3"))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	r1, _ := convert(evt("A1", &waE2E.Message{Conversation: proto.String("v1")}))
	r2, _ := convert(evt("A2", &waE2E.Message{Conversation: proto.String("second")}))
	r2.Timestamp = "2026-09-28T13:06:00Z"
	for _, r := range []Record{r1, r2} {
		if err := s.upsert(r); err != nil {
			t.Fatal(err)
		}
	}
	_ = s.setChatName(group.String(), "Family")

	// same id again with new text = edit
	r1b := r1
	r1b.Text = "v2"
	if err := s.upsert(r1b); err != nil {
		t.Fatal(err)
	}

	all, err := s.query(time.Time{}, "", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(all) != 2 || all[0].ID != "A1" || all[0].Text != "v2" || all[0].ChatName != "Family" {
		t.Fatalf("bad query: %+v", all)
	}
	since, _ := s.query(time.Date(2026, 9, 28, 14, 5, 30, 0, time.FixedZone("BST", 3600)), "", 10)
	if len(since) != 1 || since[0].ID != "A2" {
		t.Fatalf("since filter wrong: %+v", since)
	}
	other, _ := s.query(time.Time{}, "nope@g.us", 10)
	if len(other) != 0 {
		t.Fatalf("chat filter wrong: %+v", other)
	}
}
