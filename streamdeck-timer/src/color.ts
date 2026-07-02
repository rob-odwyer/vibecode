/**
 * Color interpolation for the timer ring.
 *
 * The ring shifts smoothly from green (full) through amber (halfway) to red
 * (near zero) as the fraction of time remaining decreases from 1 to 0.
 */

export interface RGB {
	r: number;
	g: number;
	b: number;
}

/** Endpoint colors of the gradient. */
export const GREEN: RGB = { r: 0x2e, g: 0xcc, b: 0x71 };
export const AMBER: RGB = { r: 0xf1, g: 0xc4, b: 0x0f };
export const RED: RGB = { r: 0xe7, g: 0x4c, b: 0x3c };

function lerp(a: number, b: number, t: number): number {
	return Math.round(a + (b - a) * t);
}

function lerpRgb(a: RGB, b: RGB, t: number): RGB {
	return { r: lerp(a.r, b.r, t), g: lerp(a.g, b.g, t), b: lerp(a.b, b.b, t) };
}

/**
 * Maps a fraction of time remaining (1 = full, 0 = empty) to a color on the
 * green → amber → red gradient. The gradient is split into two even halves so
 * that exactly 0.5 lands on pure amber.
 */
export function colorForFraction(fraction: number): RGB {
	const f = Math.max(0, Math.min(1, fraction));
	if (f >= 0.5) {
		// 1.0 → green, 0.5 → amber
		const t = (1 - f) / 0.5;
		return lerpRgb(GREEN, AMBER, t);
	}
	// 0.5 → amber, 0.0 → red
	const t = (0.5 - f) / 0.5;
	return lerpRgb(AMBER, RED, t);
}

/** Formats an RGB color as a `#rrggbb` hex string. */
export function toHex(c: RGB): string {
	const h = (n: number) => Math.max(0, Math.min(255, n)).toString(16).padStart(2, "0");
	return `#${h(c.r)}${h(c.g)}${h(c.b)}`;
}

/** Convenience: hex color directly for a fraction. */
export function hexForFraction(fraction: number): string {
	return toHex(colorForFraction(fraction));
}
