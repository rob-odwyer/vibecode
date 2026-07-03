/**
 * Renders the key face as an SVG data URI: a colored progress ring (or the
 * flashing done frame). Text is not drawn here — Stream Deck composites the
 * user's native title on top. Pure and unit-testable — no SDK imports.
 */

import { hexForFraction } from "./color.js";
import type { Status } from "./timer-model.js";

/** Key art is drawn on a 144×144 canvas (Stream Deck @2x key size). */
export const SIZE = 144;
export const CENTER = SIZE / 2;
export const RADIUS = 54;
export const STROKE = 12;
export const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export interface RenderState {
	/** Fraction of time remaining, 0..1 (drives arc length + color). */
	fraction: number;
	status: Status;
	/** For the "done" flash animation: true = bright frame, false = dark frame. */
	flashOn?: boolean;
}

/** Length of the "empty" gap so the drawn arc represents `fraction` of the ring. */
export function arcDashoffset(fraction: number, circumference = CIRCUMFERENCE): number {
	const f = Math.max(0, Math.min(1, fraction));
	return +(circumference * (1 - f)).toFixed(2);
}

export function renderSvg(state: RenderState): string {
	const { status, flashOn = true } = state;

	if (status === "done") {
		const bg = flashOn ? "#e74c3c" : "#2a0d0a";
		const ring = flashOn ? "#ffffff" : "#5c2a25";
		return svg(`
			<rect x="0" y="0" width="${SIZE}" height="${SIZE}" rx="24" fill="${bg}"/>
			<circle cx="${CENTER}" cy="${CENTER}" r="${RADIUS}" fill="none"
				stroke="${ring}" stroke-width="${STROKE}" opacity="0.9"/>
		`);
	}

	const arcColor = hexForFraction(state.fraction);
	const offset = arcDashoffset(state.fraction);
	// Paused rings are dimmed to signal the frozen state.
	const arcOpacity = status === "paused" ? 0.45 : 1;

	return svg(`
		<rect x="0" y="0" width="${SIZE}" height="${SIZE}" rx="24" fill="#17181a"/>
		<circle cx="${CENTER}" cy="${CENTER}" r="${RADIUS}" fill="none"
			stroke="#333438" stroke-width="${STROKE}"/>
		<circle cx="${CENTER}" cy="${CENTER}" r="${RADIUS}" fill="none"
			stroke="${arcColor}" stroke-width="${STROKE}" stroke-linecap="round"
			stroke-dasharray="${CIRCUMFERENCE.toFixed(2)}" stroke-dashoffset="${offset}"
			opacity="${arcOpacity}"
			transform="rotate(-90 ${CENTER} ${CENTER})"/>
	`);
}

function svg(body: string): string {
	return `<svg xmlns="http://www.w3.org/2000/svg" width="${SIZE}" height="${SIZE}" viewBox="0 0 ${SIZE} ${SIZE}">${body}</svg>`;
}

/** Encode an SVG string as a data URI suitable for `action.setImage`. */
export function svgToDataUri(svgMarkup: string): string {
	const base64 = Buffer.from(svgMarkup, "utf8").toString("base64");
	return `data:image/svg+xml;base64,${base64}`;
}
