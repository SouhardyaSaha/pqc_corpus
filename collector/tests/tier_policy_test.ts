import { assignTier } from "../tiering/policy.ts";
Deno.test("tier cutoff includes its boundary and handles zero denominators", () => {
	for (
		const [matched, total, expected] of [[148, 1000, "A"], [147, 1000, "B"], [0, 1, "B"], [
			0,
			0,
			"unrated",
		]] as const
	) {
		if (assignTier(matched, total) !== expected) throw new Error("Wrong tier");
	}
});
Deno.test("invalid search counts cannot produce a tier", () => {
	for (const [matched, total] of [[2, 1], [-1, 2], [1.5, 2], [1, 0]]) {
		let failed = false;
		try {
			assignTier(matched, total);
		} catch {
			failed = true;
		}
		if (!failed) throw new Error("Accepted invalid count");
	}
});
