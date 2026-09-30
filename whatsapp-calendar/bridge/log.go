package main

import (
	"fmt"
	"os"
	"time"

	waLog "go.mau.fi/whatsmeow/util/log"
)

// stderrLogger implements waLog.Logger and writes to stderr so that `fetch`
// can keep stdout for JSON.
type stderrLogger struct {
	module string
	level  string // DEBUG, INFO, WARN, ERROR
}

var levelRank = map[string]int{"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}

func (l *stderrLogger) enabled(level string) bool {
	return levelRank[level] >= levelRank[l.level]
}

func (l *stderrLogger) logf(level, format string, args ...any) {
	if !l.enabled(level) {
		return
	}
	fmt.Fprintf(os.Stderr, "%s %-5s [%s] %s\n", time.Now().Format("15:04:05"), level, l.module, fmt.Sprintf(format, args...))
}

func (l *stderrLogger) Debugf(format string, args ...any) { l.logf("DEBUG", format, args...) }
func (l *stderrLogger) Infof(format string, args ...any)  { l.logf("INFO", format, args...) }
func (l *stderrLogger) Warnf(format string, args ...any)  { l.logf("WARN", format, args...) }
func (l *stderrLogger) Errorf(format string, args ...any) { l.logf("ERROR", format, args...) }
func (l *stderrLogger) Sub(module string) waLog.Logger {
	return &stderrLogger{module: l.module + "/" + module, level: l.level}
}
