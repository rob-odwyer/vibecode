import { describe, expect, test } from "bun:test";

import {
	DEFAULT_MS,
	durationMs,
	formatDuration,
	fractionRemaining,
	isExpired,
	markDone,
	parseDuration,
	pause,
	press,
	remainingMs,
	reset,
	start,
	type TimerSettings,
} from "../src/timer-model.js";

const T0 = 1_000_000; // arbitrary fixed "now"

describe("parseDuration", () => {
	test("parses human-readable durations to ms", () => {
		expect(parseDuration("10s")).toBe(10_000);
		expect(parseDuration("90s")).toBe(90_000);
		expect(parseDuration("30m")).toBe(1_800_000);
		expect(parseDuration("1h 30m")).toBe(5_400_000);
		expect(parseDuration("5 min")).toBe(300_000);
		expect(parseDuration("2h")).toBe(7_200_000);
	});

	test("reads a bare number as seconds, not milliseconds", () => {
		expect(parseDuration("90")).toBe(90_000);
		expect(parseDuration("10")).toBe(10_000);
		expect(durationMs({ duration: "90" })).toBe(90_000);
	});

	test("returns null for blank or unparseable input", () => {
		expect(parseDuration("")).toBeNull();
		expect(parseDuration("   ")).toBeNull();
		expect(parseDuration(undefined)).toBeNull();
		expect(parseDuration("banana")).toBeNull();
	});
});

describe("durationMs", () => {
	test("parses the duration string", () => {
		expect(durationMs({ duration: "1m 30s" })).toBe(90_000);
		expect(durationMs({ duration: "10s" })).toBe(10_000);
		expect(durationMs({ duration: "30m" })).toBe(1_800_000);
		expect(durationMs({ duration: "1h 30m" })).toBe(5_400_000);
	});

	test("falls back to the 5m default when blank or unparseable", () => {
		expect(durationMs({})).toBe(DEFAULT_MS);
		expect(durationMs({ duration: "" })).toBe(DEFAULT_MS);
		expect(durationMs({ duration: "not a duration" })).toBe(DEFAULT_MS);
	});
});

describe("formatDuration", () => {
	test("renders a compact human string", () => {
		expect(formatDuration(10_000)).toBe("10s");
		expect(formatDuration(90_000)).toBe("1m 30s");
		expect(formatDuration(1_800_000)).toBe("30m");
		expect(formatDuration(5_400_000)).toBe("1h 30m");
		expect(formatDuration(3_600_000)).toBe("1h");
		expect(formatDuration(0)).toBe("0s");
	});
});

describe("start / pause / resume", () => {
	test("start sets an absolute end timestamp", () => {
		const s = start({ duration: "1m" }, T0);
		expect(s.status).toBe("running");
		expect(s.endTimestamp).toBe(T0 + 60_000);
		expect(s.remainingMs).toBeUndefined();
	});

	test("remaining derives from the clock while running", () => {
		const s = start({ duration: "1m" }, T0);
		expect(remainingMs(s, T0 + 20_000)).toBe(40_000);
		expect(fractionRemaining(s, T0 + 30_000)).toBeCloseTo(0.5, 5);
	});

	test("pause banks the remaining time and clears the timestamp", () => {
		const running = start({ duration: "1m" }, T0);
		const paused = pause(running, T0 + 15_000);
		expect(paused.status).toBe("paused");
		expect(paused.remainingMs).toBe(45_000);
		expect(paused.endTimestamp).toBeUndefined();
		// Paused time does not advance with the clock.
		expect(remainingMs(paused, T0 + 999_000)).toBe(45_000);
	});

	test("resuming a paused timer keeps the banked remaining time", () => {
		const paused: TimerSettings = { status: "paused", remainingMs: 45_000, duration: "1m" };
		const resumed = start(paused, T0 + 100_000);
		expect(resumed.status).toBe("running");
		expect(resumed.endTimestamp).toBe(T0 + 100_000 + 45_000);
	});
});

describe("reset / markDone", () => {
	test("reset returns a full idle timer that tracks the current duration", () => {
		const s = reset({ duration: "2m", status: "running", endTimestamp: 42 });
		expect(s.status).toBe("idle");
		expect(s.remainingMs).toBeUndefined();
		expect(s.endTimestamp).toBeUndefined();
		expect(fractionRemaining(s, T0)).toBe(1);
		// Editing the duration after reset is reflected immediately (still full).
		expect(fractionRemaining({ ...s, duration: "10m" }, T0)).toBe(1);
	});

	test("markDone yields an empty, finished timer", () => {
		const s = markDone({ duration: "1m", status: "running", endTimestamp: T0 });
		expect(s.status).toBe("done");
		expect(remainingMs(s, T0 + 5_000)).toBe(0);
		expect(fractionRemaining(s, T0)).toBe(0);
	});
});

describe("isExpired", () => {
	test("true only for a running timer past its end", () => {
		const running = start({ duration: "1m" }, T0);
		expect(isExpired(running, T0 + 59_000)).toBe(false);
		expect(isExpired(running, T0 + 60_000)).toBe(true);
		expect(isExpired(running, T0 + 61_000)).toBe(true);
	});

	test("never expired when idle/paused/done", () => {
		expect(isExpired({ status: "idle", duration: "1m" }, T0)).toBe(false);
		expect(isExpired({ status: "paused", remainingMs: 0 }, T0)).toBe(false);
		expect(isExpired({ status: "done" }, T0)).toBe(false);
	});
});

describe("press (short-press state machine)", () => {
	test("idle → running", () => {
		expect(press({ status: "idle", duration: "1m" }, T0).status).toBe("running");
	});

	test("running → paused", () => {
		const running = start({ duration: "1m" }, T0);
		expect(press(running, T0 + 10_000).status).toBe("paused");
	});

	test("paused → running (resume)", () => {
		expect(press({ status: "paused", remainingMs: 30_000 }, T0).status).toBe("running");
	});

	test("done → idle (dismiss to full)", () => {
		const dismissed = press({ status: "done", duration: "3m" }, T0);
		expect(dismissed.status).toBe("idle");
		expect(dismissed.remainingMs).toBeUndefined();
		expect(fractionRemaining(dismissed, T0)).toBe(1);
	});

	test("unconfigured (undefined status) starts", () => {
		expect(press({ duration: "1m" }, T0).status).toBe("running");
	});
});
