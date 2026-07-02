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
	test("running frame embeds the green color and the title", () => {
		const svg = renderSvg({ title: "Tea", fraction: 1, status: "running" });
		expect(svg).toContain("<svg");
		expect(svg).toContain("#2ecc71"); // green at full
		expect(svg).toContain(">Tea<");
		expect(svg).toContain('stroke-dashoffset="0"');
	});

	test("near-zero running frame trends red", () => {
		const svg = renderSvg({ title: "X", fraction: 0.05, status: "running" });
		expect(svg).toContain("#e"); // red-ish stroke color
	});

	test("done frame shows DONE and flips colors between flash frames", () => {
		const on = renderSvg({ title: "ignored", fraction: 0, status: "done", flashOn: true });
		const off = renderSvg({ title: "ignored", fraction: 0, status: "done", flashOn: false });
		expect(on).toContain(">DONE<");
		expect(off).toContain(">DONE<");
		expect(on).toContain("#e74c3c"); // bright red background when flashOn
		expect(on).not.toEqual(off); // frames differ so the key visibly flashes
	});

	test("escapes XML-sensitive characters in the title", () => {
		const svg = renderSvg({ title: "A&B<C>", fraction: 1, status: "idle" });
		expect(svg).toContain("A&amp;B&lt;C&gt;");
		expect(svg).not.toContain("A&B<C>");
	});

	test("paused frame dims the arc", () => {
		const svg = renderSvg({ title: "Nap", fraction: 0.8, status: "paused" });
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
