/**
 * Pure timer state machine and time math.
 *
 * All functions are side-effect free so they can be unit tested without the
 * Stream Deck runtime. `now` is always passed in (epoch milliseconds) rather
 * than read from the clock internally.
 *
 * Remaining time while running is derived from an absolute `endTimestamp`, not
 * a decremented counter, so the display stays correct across profile switches,
 * app restarts, and dropped render ticks.
 */

export type Status = "idle" | "running" | "paused" | "done";

// Declared as a `type` (not `interface`) so it satisfies the SDK's
// `JsonObject` index-signature constraint on `SingletonAction<T>`.
export type TimerSettings = {
	/** User-configured title shown inside the ring (Property Inspector). */
	title?: string;
	/** User-configured duration (Property Inspector). */
	minutes?: number | string;
	seconds?: number | string;

	/** Persisted runtime state so a running timer survives reloads. */
	status?: Status;
	/** Epoch ms at which the timer completes (only while running). */
	endTimestamp?: number;
	/** Remaining ms (only while paused or idle). */
	remainingMs?: number;
};

export const DEFAULT_MINUTES = 5;
export const DEFAULT_SECONDS = 0;

function num(value: number | string | undefined, fallback: number): number {
	if (value === undefined || value === null || value === "") return fallback;
	const n = Number(value);
	return Number.isFinite(n) && n >= 0 ? n : fallback;
}

/** Configured total duration in ms, falling back to the default when unset/zero. */
export function durationMs(s: TimerSettings): number {
	const m = num(s.minutes, DEFAULT_MINUTES);
	const sec = num(s.seconds, DEFAULT_SECONDS);
	const total = Math.round((m * 60 + sec) * 1000);
	return total > 0 ? total : DEFAULT_MINUTES * 60 * 1000;
}

/** Current remaining time in ms for any status. */
export function remainingMs(s: TimerSettings, now: number): number {
	const status = s.status ?? "idle";
	if (status === "running" && s.endTimestamp != null) {
		return Math.max(0, s.endTimestamp - now);
	}
	if (status === "paused" && s.remainingMs != null) {
		return Math.max(0, s.remainingMs);
	}
	if (status === "done") return 0;
	// idle
	return s.remainingMs ?? durationMs(s);
}

/** Fraction of the configured duration still remaining, clamped to [0, 1]. */
export function fractionRemaining(s: TimerSettings, now: number): number {
	const total = durationMs(s);
	if (total <= 0) return 0;
	return Math.max(0, Math.min(1, remainingMs(s, now) / total));
}

// --- Transitions: each returns a new settings object, never mutating input. ---

/** Begin (or resume) counting down. */
export function start(s: TimerSettings, now: number): TimerSettings {
	const rem = s.status === "paused" && s.remainingMs != null ? s.remainingMs : durationMs(s);
	return { ...s, status: "running", endTimestamp: now + rem, remainingMs: undefined };
}

/** Freeze the countdown, banking the remaining time. */
export function pause(s: TimerSettings, now: number): TimerSettings {
	return { ...s, status: "paused", remainingMs: remainingMs(s, now), endTimestamp: undefined };
}

/** Return to a fresh, full, idle timer. */
export function reset(s: TimerSettings): TimerSettings {
	return { ...s, status: "idle", remainingMs: durationMs(s), endTimestamp: undefined };
}

/** Enter the finished/flashing state. */
export function markDone(s: TimerSettings): TimerSettings {
	return { ...s, status: "done", remainingMs: 0, endTimestamp: undefined };
}

/**
 * Result of a short key press, given the current status:
 *   idle    → start
 *   running → pause
 *   paused  → resume (start)
 *   done    → dismiss (reset to full idle)
 */
export function press(s: TimerSettings, now: number): TimerSettings {
	switch (s.status ?? "idle") {
		case "running":
			return pause(s, now);
		case "done":
			return reset(s);
		case "idle":
		case "paused":
		default:
			return start(s, now);
	}
}

/** True once a running timer has reached zero and should flip to `done`. */
export function isExpired(s: TimerSettings, now: number): boolean {
	return (s.status ?? "idle") === "running" && remainingMs(s, now) <= 0;
}
