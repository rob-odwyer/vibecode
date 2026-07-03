import { describe, expect, test } from "bun:test";

import { arcDashoffset, CIRCUMFERENCE, renderSvg, svgToDataUri } from "../src/render.js";

describe("arcDashoffset", () => {
	test("full ring when fraction is 1", () => {
		expect(arcDashoffset(1)).toBe(0);
	});

	test("empty ring when fraction is 0", () => {
		expect(arcDashoffset(0)).toBeCloseTo(CIRCUMFERENCE, 1);
	});

	test("half ring at fraction 0.5", () => {
		expect(arcDashoffset(0.5)).toBeCloseTo(CIRCUMFERENCE / 2, 1);
	});

	test("clamps out-of-range fractions", () => {
		expect(arcDashoffset(5)).toBe(0);
		expect(arcDashoffset(-5)).toBeCloseTo(CIRCUMFERENCE, 1);
	});
});

describe("renderSvg", () => {
	test("running frame embeds the green color at full", () => {
		const svg = renderSvg({ fraction: 1, status: "running" });
		expect(svg).toContain("<svg");
		expect(svg).toContain("#2ecc71"); // green at full
		expect(svg).toContain('stroke-dashoffset="0"');
	});

	test("near-zero running frame trends red", () => {
		const svg = renderSvg({ fraction: 0.05, status: "running" });
		expect(svg).toContain("#e"); // red-ish stroke color
	});

	test("done frame flips colors between flash frames and draws no text", () => {
		const on = renderSvg({ fraction: 0, status: "done", flashOn: true });
		const off = renderSvg({ fraction: 0, status: "done", flashOn: false });
		expect(on).toContain("#e74c3c"); // bright red background when flashOn
		expect(on).not.toEqual(off); // frames differ so the key visibly flashes
		// The native Stream Deck title is composited on top — no <text> in the SVG.
		expect(on).not.toContain("<text");
		expect(off).not.toContain("<text");
	});

	test("paused frame dims the arc", () => {
		const svg = renderSvg({ fraction: 0.8, status: "paused" });
		expect(svg).toContain('opacity="0.45"');
	});
});

describe("svgToDataUri", () => {
	test("produces a base64 svg data URI that round-trips", () => {
		const uri = svgToDataUri("<svg/>");
		expect(uri.startsWith("data:image/svg+xml;base64,")).toBe(true);
		const decoded = Buffer.from(uri.split(",")[1], "base64").toString("utf8");
		expect(decoded).toBe("<svg/>");
	});
});
