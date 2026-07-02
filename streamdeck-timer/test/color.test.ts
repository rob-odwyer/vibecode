import { describe, expect, test } from "bun:test";

import { AMBER, colorForFraction, GREEN, hexForFraction, RED, toHex } from "../src/color.js";

describe("colorForFraction", () => {
	test("full time remaining is green", () => {
		expect(colorForFraction(1)).toEqual(GREEN);
		expect(hexForFraction(1)).toBe("#2ecc71");
	});

	test("half remaining is amber", () => {
		expect(colorForFraction(0.5)).toEqual(AMBER);
		expect(hexForFraction(0.5)).toBe("#f1c40f");
	});

	test("no time remaining is red", () => {
		expect(colorForFraction(0)).toEqual(RED);
		expect(hexForFraction(0)).toBe("#e74c3c");
	});

	test("clamps out-of-range fractions", () => {
		expect(colorForFraction(2)).toEqual(GREEN);
		expect(colorForFraction(-1)).toEqual(RED);
	});

	test("green channel fades monotonically as time drops", () => {
		// Across green → amber → red the green channel only ever decreases,
		// giving the ring its steady "cooling off" progression.
		const greens = [1, 0.75, 0.5, 0.25, 0].map((f) => colorForFraction(f).g);
		for (let i = 1; i < greens.length; i++) {
			expect(greens[i]).toBeLessThanOrEqual(greens[i - 1]);
		}
	});
});

describe("toHex", () => {
	test("pads single-digit channels and clamps", () => {
		expect(toHex({ r: 0, g: 5, b: 255 })).toBe("#0005ff");
		expect(toHex({ r: -10, g: 300, b: 16 })).toBe("#00ff10");
	});
});
