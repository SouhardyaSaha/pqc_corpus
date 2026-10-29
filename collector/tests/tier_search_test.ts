/** Tier search classification against canned search results; no network or tokens. */
import { join } from "@std/path";
import { classifyRepository, type TierSearchTarget } from "../tiering/classify.ts";
import { buildSearchQuery } from "../tiering/matching.ts";
import { FakeSearch } from "./fake_github.ts";

function assertEquals(actual: unknown, expected: unknown, label = ""): void {
	if (JSON.stringify(actual) !== JSON.stringify(expected)) {
		throw new Error(`${label} expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
	}
}

async function classify(search: FakeSearch, terms: string[]) {
	const run = await Deno.makeTempDir();
	const target: TierSearchTarget = {
		run,
		repo: "fixture/project",
		terms,
		cutoff: 0.148,
		policySha256: "h",
		planPath: join(run, "tier_plans", "fixture__project.json"),
		cacheDir: join(run, "cache"),
	};
	await Deno.mkdir(target.cacheDir, { recursive: true });
	await classifyRepository(target, search, () => {}, 0);
	const plan = JSON.parse(await Deno.readTextFile(target.planPath));
	return { run, target, plan };
}

Deno.test("search queries scope Tier B selection to titles and bodies", () => {
	assertEquals(
		buildSearchQuery("o/r", "pr", "title_body", ["ML-KEM", "Kyber"]),
		'repo:o/r is:pr in:title,body "ML-KEM" OR "Kyber"',
	);
	assertEquals(
		buildSearchQuery("o/r", "issue", "any", ["PQC"], [0, 1000]),
		'repo:o/r is:issue in:title,body,comments "PQC" created:1970-01-01T00:00:00Z..1970-01-01T00:00:01Z',
	);
});

Deno.test("capped queries are split and unioned without losing matches", async () => {
	const search = new FakeSearch({ capped: [], "ML-KEM": [1, 2], Kyber: [2, 3, 101] });
	const { run, plan } = await classify(search, ["ML-KEM", "capped", "Kyber"]);
	assertEquals(plan.any_pr_numbers, [1, 2, 3], "PR union");
	assertEquals(plan.any_issue_numbers, [101], "issue union");
	assertEquals(plan.tier, "B", "tier");
	await Deno.remove(run, { recursive: true });
});

Deno.test("an existing plan is reused and cached queries are not repeated", async () => {
	const search = new FakeSearch({ "ML-KEM": [1] }, { pullRequests: 2, issues: 0 });
	const { run, target, plan } = await classify(search, ["ML-KEM"]);
	assertEquals(plan.tier, "A", "tier");
	const before = search.queries.length;
	await classifyRepository(target, search, () => {}, 0);
	assertEquals(search.queries.length, before, "queries after reuse");
	await Deno.remove(run, { recursive: true });
});
