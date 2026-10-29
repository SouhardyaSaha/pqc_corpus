import { assignCorpus } from "../search/policy.ts";
Deno.test("corpus cutoff includes its boundary and handles zero denominators", () => {
	for (
		const [matched, total, expected] of [[148, 1000, "A"], [147, 1000, "B"], [0, 1, "B"], [
			0,
			0,
			"unrated",
		]] as const
	) {
		if (assignCorpus(matched, total) !== expected) throw new Error("Wrong corpus");
	}
});
Deno.test("invalid search counts cannot produce a corpus", () => {
	for (const [matched, total] of [[2, 1], [-1, 2], [1.5, 2], [1, 0]]) {
		let failed = false;
		try {
			assignCorpus(matched, total);
		} catch {
			failed = true;
		}
		if (!failed) throw new Error("Accepted invalid count");
	}
});
