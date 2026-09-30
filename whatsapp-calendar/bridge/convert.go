package main

import (
	"fmt"
	"strings"
	"time"

	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

// convert turns a whatsmeow message event into a Record. ok is false for
// things that carry no calendar-relevant content (reactions, receipts,
// key distribution, deletions, ...).
func convert(evt *events.Message) (Record, bool) {
	m := evt.Message
	id := string(evt.Info.ID)

	// Edits arrive as a ProtocolMessage pointing at the original id. Store the
	// new content under the original id so the agent sees the final text.
	if pm := m.GetProtocolMessage(); pm != nil {
		switch pm.GetType() {
		case waE2E.ProtocolMessage_MESSAGE_EDIT:
			if pm.GetEditedMessage() == nil {
				return Record{}, false
			}
			id = pm.GetKey().GetID()
			m = pm.GetEditedMessage()
		default:
			return Record{}, false
		}
	}

	text, media, ok := extractText(m)
	if !ok {
		return Record{}, false
	}

	sender := evt.Info.PushName
	if evt.Info.IsFromMe {
		sender = "me"
	} else if sender == "" {
		sender = senderLabel(evt.Info.Sender)
	}

	rec := Record{
		ID:        id,
		ChatID:    evt.Info.Chat.String(),
		Sender:    sender,
		Timestamp: evt.Info.Timestamp.UTC().Format(time.RFC3339),
		Text:      text,
		FromMe:    evt.Info.IsFromMe,
		Raw:       m,
	}
	if media != "" {
		rec.MediaType = &media
	}
	if ci := contextOf(m); ci != nil && ci.GetStanzaID() != "" {
		s := ci.GetStanzaID()
		rec.ReplyTo = &s
	}
	return rec, true
}

func senderLabel(j types.JID) string {
	if j.User != "" {
		return j.User
	}
	return j.String()
}

// extractText returns the human-readable content of a message and a media
// type label ("" for plain text).
func extractText(m *waE2E.Message) (text, media string, ok bool) {
	switch {
	case m == nil:
		return "", "", false
	case m.GetConversation() != "":
		return m.GetConversation(), "", true
	case m.GetExtendedTextMessage() != nil:
		return m.GetExtendedTextMessage().GetText(), "", true
	case m.GetImageMessage() != nil:
		return captionOr(m.GetImageMessage().GetCaption(), "image"), "image", true
	case m.GetVideoMessage() != nil:
		return captionOr(m.GetVideoMessage().GetCaption(), "video"), "video", true
	case m.GetDocumentMessage() != nil:
		d := m.GetDocumentMessage()
		t := d.GetCaption()
		if t == "" {
			t = "[document] " + d.GetFileName()
		}
		return t, "document", true
	case m.GetAudioMessage() != nil:
		return "[voice message]", "audio", true
	case m.GetStickerMessage() != nil:
		return "", "", false
	case m.GetLocationMessage() != nil:
		return formatLocation(m.GetLocationMessage()), "location", true
	case m.GetLiveLocationMessage() != nil:
		return "[live location] " + m.GetLiveLocationMessage().GetCaption(), "location", true
	case m.GetContactMessage() != nil:
		return "[contact] " + m.GetContactMessage().GetDisplayName(), "contact", true
	case m.GetEventMessage() != nil:
		return formatEvent(m.GetEventMessage()), "event", true
	case m.GetPollCreationMessageV3() != nil:
		return formatPoll(m.GetPollCreationMessageV3()), "poll", true
	case m.GetPollCreationMessageV2() != nil:
		return formatPoll(m.GetPollCreationMessageV2()), "poll", true
	case m.GetPollCreationMessage() != nil:
		return formatPoll(m.GetPollCreationMessage()), "poll", true
	case m.GetReactionMessage() != nil, m.GetSenderKeyDistributionMessage() != nil,
		m.GetPollUpdateMessage() != nil, m.GetEncReactionMessage() != nil:
		return "", "", false
	}
	return "", "", false
}

func captionOr(caption, kind string) string {
	if caption != "" {
		return caption
	}
	return "[" + kind + "]"
}

func formatLocation(l *waE2E.LocationMessage) string {
	parts := []string{"[location]"}
	if l.GetName() != "" {
		parts = append(parts, l.GetName())
	}
	if l.GetAddress() != "" {
		parts = append(parts, l.GetAddress())
	}
	parts = append(parts, fmt.Sprintf("(%.5f,%.5f)", l.GetDegreesLatitude(), l.GetDegreesLongitude()))
	return strings.Join(parts, " ")
}

// formatEvent renders WhatsApp's native group "Event" messages. These carry
// structured start/end times, so they are rendered in a fixed shape the
// agent can copy verbatim.
func formatEvent(e *waE2E.EventMessage) string {
	loc := renderTZ()
	var sb strings.Builder
	if e.GetIsCanceled() {
		sb.WriteString("[event CANCELLED] ")
	} else {
		sb.WriteString("[event] ")
	}
	sb.WriteString(e.GetName())
	if e.GetStartTime() != 0 {
		sb.WriteString("\nstart: " + time.Unix(e.GetStartTime(), 0).In(loc).Format(time.RFC3339))
	}
	if e.GetEndTime() != 0 {
		sb.WriteString("\nend: " + time.Unix(e.GetEndTime(), 0).In(loc).Format(time.RFC3339))
	}
	if l := e.GetLocation(); l != nil && (l.GetName() != "" || l.GetAddress() != "") {
		sb.WriteString("\nlocation: " + strings.TrimSpace(l.GetName()+" "+l.GetAddress()))
	}
	if e.GetDescription() != "" {
		sb.WriteString("\n" + e.GetDescription())
	}
	if e.GetJoinLink() != "" {
		sb.WriteString("\nlink: " + e.GetJoinLink())
	}
	return sb.String()
}

func formatPoll(p *waE2E.PollCreationMessage) string {
	opts := make([]string, 0, len(p.GetOptions()))
	for _, o := range p.GetOptions() {
		opts = append(opts, o.GetOptionName())
	}
	return "[poll] " + p.GetName() + "\n- " + strings.Join(opts, "\n- ")
}

func contextOf(m *waE2E.Message) *waE2E.ContextInfo {
	switch {
	case m.GetExtendedTextMessage() != nil:
		return m.GetExtendedTextMessage().GetContextInfo()
	case m.GetImageMessage() != nil:
		return m.GetImageMessage().GetContextInfo()
	case m.GetVideoMessage() != nil:
		return m.GetVideoMessage().GetContextInfo()
	case m.GetDocumentMessage() != nil:
		return m.GetDocumentMessage().GetContextInfo()
	case m.GetAudioMessage() != nil:
		return m.GetAudioMessage().GetContextInfo()
	case m.GetLocationMessage() != nil:
		return m.GetLocationMessage().GetContextInfo()
	case m.GetEventMessage() != nil:
		return m.GetEventMessage().GetContextInfo()
	case m.GetPollCreationMessageV3() != nil:
		return m.GetPollCreationMessageV3().GetContextInfo()
	case m.GetPollCreationMessage() != nil:
		return m.GetPollCreationMessage().GetContextInfo()
	}
	return nil
}

func renderTZ() *time.Location {
	if name := envOr("TIMEZONE", ""); name != "" {
		if loc, err := time.LoadLocation(name); err == nil {
			return loc
		}
	}
	return time.UTC
}
