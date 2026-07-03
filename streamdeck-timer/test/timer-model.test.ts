import { describe, expect, test } from "bun:test";

import {
	DEFAULT_MINUTES,
	durationMs,
	fractionRemaining,
	isExpired,
	markDone,
	pause,
	press,
	remainingMs,
	reset,
	start,
	type TimerSettings,
} from "../src/timer-model.js";

const T0 = 1_000_000; // arbitrary fixed "now"

describe("durationMs", () => {
	test("defaults to 5 minutes when unset", () => {
		expect(durationMs({})).toBe(DEFAULT_MINUTES * 60_000);
	});

	test("combines minutes and seconds", () => {
		expect(durationMs({ minutes: 1, seconds: 30 })).toBe(90_000);
	});

	test("coerces string inputs from the Property Inspector", () => {
		expect(durationMs({ minutes: "2", seconds: "0" })).toBe(120_000);
	});

	test("a seconds-only timer does not pick up the default minutes", () => {
		// Regression: a blank minutes field must count as 0, not 5 minutes.
		expect(durationMs({ seconds: 10 })).toBe(10_000);
		expect(durationMs({ minutes: "", seconds: "10" })).toBe(10_000);
	});

	test("a minutes-only timer leaves seconds at zero", () => {
		expect(durationMs({ minutes: 30 })).toBe(1_800_000);
	});

	test("falls back to default only when nothing is configured", () => {
		expect(durationMs({ minutes: 0, seconds: 0 })).toBe(DEFAULT_MINUTES * 60_000);
		expect(durationMs({ minutes: "abc" })).toBe(DEFAULT_MINUTES * 60_000);
		expect(durationMs({})).toBe(DEFAULT_MINUTES * 60_000);
	});
});

describe("start / pause / resume", () => {
	test("start sets an absolute end timestamp", () => {
		const s = start({ minutes: 1, seconds: 0 }, T0);
		expect(s.status).toBe("running");
		expect(s.endTimestamp).toBe(T0 + 60_000);
		expect(s.remainingMs).toBeUndefined();
	});

	test("remaining derives from the clock while running", () => {
		const s = start({ minutes: 1, seconds: 0 }, T0);
		expect(remainingMs(s, T0 + 20_000)).toBe(40_000);
		expect(fractionRemaining(s, T0 + 30_000)).toBeCloseTo(0.5, 5);
	});

	test("pause banks the remaining time and clears the timestamp", () => {
		const running = start({ minutes: 1, seconds: 0 }, T0);
		const paused = pause(running, T0 + 15_000);
		expect(paused.status).toBe("paused");
		expect(paused.remainingMs).toBe(45_000);
		expect(paused.endTimestamp).toBeUndefined();
		// Paused time does not advance with the clock.
		expect(remainingMs(paused, T0 + 999_000)).toBe(45_000);
	});

	test("resuming a paused timer keeps the banked remaining time", () => {
		const paused: TimerSettings = { status: "paused", remainingMs: 45_000, minutes: 1 };
		const resumed = start(paused, T0 + 100_000);
		expect(resumed.status).toBe("running");
		expect(resumed.endTimestamp).toBe(T0 + 100_000 + 45_000);
	});
});

describe("reset / markDone", () => {
	test("reset returns a full idle timer", () => {
		const s = reset({ minutes: 2, seconds: 0, status: "running", endTimestamp: 42 });
		expect(s.status).toBe("idle");
		expect(s.remainingMs).toBe(120_000);
		expect(s.endTimestamp).toBeUndefined();
		expect(fractionRemaining(s, T0)).toBe(1);
	});

	test("markDone yields an empty, finished timer", () => {
		const s = markDone({ minutes: 1, status: "running", endTimestamp: T0 });
		expect(s.status).toBe("done");
		expect(remainingMs(s, T0 + 5_000)).toBe(0);
		expect(fractionRemaining(s, T0)).toBe(0);
	});
});

describe("isExpired", () => {
	test("true only for a running timer past its end", () => {
		const running = start({ minutes: 1 }, T0);
		expect(isExpired(running, T0 + 59_000)).toBe(false);
		expect(isExpired(running, T0 + 60_000)).toBe(true);
		expect(isExpired(running, T0 + 61_000)).toBe(true);
	});

	test("never expired when idle/paused/done", () => {
		expect(isExpired({ status: "idle", minutes: 1 }, T0)).toBe(false);
		expect(isExpired({ status: "paused", remainingMs: 0 }, T0)).toBe(false);
		expect(isExpired({ status: "done" }, T0)).toBe(false);
	});
});

describe("press (short-press state machine)", () => {
	test("idle → running", () => {
		expect(press({ status: "idle", minutes: 1 }, T0).status).toBe("running");
	});

	test("running → paused", () => {
		const running = start({ minutes: 1 }, T0);
		expect(press(running, T0 + 10_000).status).toBe("paused");
	});

	test("paused → running (resume)", () => {
		expect(press({ status: "paused", remainingMs: 30_000 }, T0).status).toBe("running");
	});

	test("done → idle (dismiss to full)", () => {
		const dismissed = press({ status: "done", minutes: 3 }, T0);
		expect(dismissed.status).toBe("idle");
		expect(dismissed.remainingMs).toBe(180_000);
	});

	test("unconfigured (undefined status) starts", () => {
		expect(press({ minutes: 1 }, T0).status).toBe("running");
	});
});
