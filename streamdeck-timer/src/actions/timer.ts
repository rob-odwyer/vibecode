import {
	action,
	SingletonAction,
	type DidReceiveSettingsEvent,
	type KeyDownEvent,
	type KeyUpEvent,
	type WillAppearEvent,
	type WillDisappearEvent,
} from "@elgato/streamdeck";
import type { DialAction, KeyAction } from "@elgato/streamdeck";

import { renderSvg, svgToDataUri } from "../render.js";
import {
	fractionRemaining,
	isExpired,
	markDone,
	press,
	reset,
	remainingMs,
	type Status,
	type TimerSettings,
} from "../timer-model.js";

/** How long a key must be held (ms) before it counts as a reset instead of a press. */
const HOLD_MS = 700;
/** Redraw cadence while running (ms) — 4 fps keeps the ring smooth without churn. */
const TICK_MS = 250;
/** Flash cadence in the finished state (ms). */
const FLASH_MS = 500;

/** A drawable action target — both key and dial actions expose setImage/setTitle. */
type TimerTarget = KeyAction<TimerSettings> | DialAction<TimerSettings>;

/** Per-key-instance runtime state, kept in the plugin process (not persisted). */
type Runtime = {
	interval?: ReturnType<typeof setInterval>;
	holdTimer?: ReturnType<typeof setTimeout>;
	/** Set when the hold-to-reset fired, so the following keyUp is ignored. */
	didHold: boolean;
	/** Current frame of the done-state flash. */
	flashOn: boolean;
	/** Cached settings so the render tick avoids a round-trip every frame. */
	settings: TimerSettings;
};

@action({ UUID: "com.robodwyer.timer.countdown" })
export class TimerAction extends SingletonAction<TimerSettings> {
	private readonly runtimes = new Map<string, Runtime>();

	private runtime(id: string): Runtime {
		let r = this.runtimes.get(id);
		if (!r) {
			r = { didHold: false, flashOn: true, settings: {} };
			this.runtimes.set(id, r);
		}
		return r;
	}

	override onWillAppear(ev: WillAppearEvent<TimerSettings>): Promise<void> {
		const r = this.runtime(ev.action.id);
		r.settings = ev.payload.settings ?? {};
		return this.apply(ev.action, r.settings, { persist: false });
	}

	override onWillDisappear(ev: WillDisappearEvent<TimerSettings>): void {
		this.stopLoop(ev.action.id);
		this.runtimes.delete(ev.action.id);
	}

	override async onDidReceiveSettings(ev: DidReceiveSettingsEvent<TimerSettings>): Promise<void> {
		// The Property Inspector only edits title/duration. Keep the live runtime
		// fields (status/timestamps) and graft the new config on top.
		const r = this.runtime(ev.action.id);
		const incoming = ev.payload.settings ?? {};
		const merged: TimerSettings = {
			...r.settings,
			title: incoming.title,
			minutes: incoming.minutes,
			seconds: incoming.seconds,
		};
		// If the timer isn't running, adopt the new duration immediately.
		const status = merged.status ?? "idle";
		const next = status === "running" || status === "paused" ? merged : reset(merged);
		await this.apply(ev.action, next, { persist: true });
	}

	override onKeyDown(ev: KeyDownEvent<TimerSettings>): void {
		const r = this.runtime(ev.action.id);
		r.didHold = false;
		clearTimeout(r.holdTimer);
		r.holdTimer = setTimeout(() => {
			r.didHold = true;
			void this.apply(ev.action, reset(r.settings), { persist: true });
		}, HOLD_MS);
	}

	override async onKeyUp(ev: KeyUpEvent<TimerSettings>): Promise<void> {
		const r = this.runtime(ev.action.id);
		clearTimeout(r.holdTimer);
		r.holdTimer = undefined;
		if (r.didHold) {
			// The hold already handled this gesture as a reset.
			r.didHold = false;
			return;
		}
		await this.apply(ev.action, press(r.settings, Date.now()), { persist: true });
	}

	/**
	 * Commits a new settings state: caches it, optionally persists it, redraws
	 * the key, and (re)starts the appropriate render/flash loop.
	 */
	private async apply(
		action: TimerTarget,
		settings: TimerSettings,
		opts: { persist: boolean },
	): Promise<void> {
		const r = this.runtime(action.id);
		r.settings = settings;
		if ((settings.status ?? "idle") === "done") {
			r.flashOn = true;
		}
		if (opts.persist) {
			await action.setSettings(settings);
		}
		await this.render(action, settings, r.flashOn);
		this.syncLoop(action, settings);
	}

	/** Draws the current key face. */
	private async render(action: TimerTarget, settings: TimerSettings, flashOn: boolean): Promise<void> {
		const status: Status = settings.status ?? "idle";
		const state = {
			title: status === "done" ? "DONE" : settings.title ?? "",
			fraction: fractionRemaining(settings, Date.now()),
			status,
			flashOn,
		};
		await action.setImage(svgToDataUri(renderSvg(state)));
		// The title is drawn inside the SVG, so clear the native title layer.
		await action.setTitle("");
	}

	/** Starts/stops the per-status interval loop (running = tick, done = flash). */
	private syncLoop(action: TimerTarget, settings: TimerSettings): void {
		const r = this.runtime(action.id);
		this.stopLoop(action.id);
		const status: Status = settings.status ?? "idle";

		if (status === "running") {
			r.interval = setInterval(() => void this.onTick(action), TICK_MS);
		} else if (status === "done") {
			r.interval = setInterval(() => {
				r.flashOn = !r.flashOn;
				void this.render(action, r.settings, r.flashOn);
			}, FLASH_MS);
		}
		// idle & paused are static — no loop.
	}

	/** One running-state frame: redraw, and flip to done when time expires. */
	private async onTick(action: TimerTarget): Promise<void> {
		const r = this.runtime(action.id);
		const now = Date.now();
		if (isExpired(r.settings, now) || remainingMs(r.settings, now) <= 0) {
			await this.apply(action, markDone(r.settings), { persist: true });
			return;
		}
		await this.render(action, r.settings, r.flashOn);
	}

	private stopLoop(id: string): void {
		const r = this.runtimes.get(id);
		if (r?.interval) {
			clearInterval(r.interval);
			r.interval = undefined;
		}
	}
}
