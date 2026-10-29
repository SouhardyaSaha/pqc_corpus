/** Collector phases against canned GitHub responses; no network or tokens. */
import { join } from "@std/path";
import type { TierPlan } from "../api/config.ts";
import { collectPhases } from "../api/phases.ts";
import { CollectorSession } from "../api/session.ts";
import { MiningStore } from "../api/store.ts";
import { FakeGitHub } from "./fake_github.ts";

function assertEquals(actual: unknown, expected: unknown, label = ""): void {
	if (JSON.stringify(actual) !== JSON.stringify(expected)) {
		throw new Error(`${label} expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
	}
}

const MANIFEST = { repositories: [{ repo: "fixture/project" }] };

async function collect(tierPlan?: TierPlan) {
	const run = await Deno.makeTempDir();
	const store = new MiningStore(join(run, "github.sqlite"));
	const github = new FakeGitHub();
	const session = new CollectorSession(run, store, github, { requested: false }, {}, 0);
	const code = await collectPhases(session, MANIFEST, tierPlan, 10);
	const counts = Object.fromEntries(
		store.recordCounts().map((row) => [String(row.kind), Number(row.records)]),
	);
	const failures = store.failures().map((row) => `${row.stage}: ${row.error}`);
	const status = JSON.parse(await Deno.readTextFile(join(run, "api_status.json")));
	store.close();
	await Deno.remove(run, { recursive: true });
	return { code, counts, failures, status, requests: github.requests };
}

Deno.test("raw run keeps PR copies out of issues and completes multi-page commits", async () => {
	const result = await collect();
	assertEquals(result.counts.pull, 3, "pulls");
	assertEquals(result.counts.issue, 1, "issues");
	assertEquals(result.counts.pr_issue, 3, "PR copies from the issue list");
	// PR 1: 1 link; PR 2: 100 + 1 across two pages; PR 3: 1 saved of 5 reported.
	assertEquals(result.counts.pr_commit, 103, "commit links");
});

Deno.test("a truncated commit list is recorded as a gap, never marked complete", async () => {
	const result = await collect();
	assertEquals(result.code, 2, "exit code");
	assertEquals(result.status.status, "completed_with_gaps", "status");
	assertEquals(result.failures, [
		"pr:3: Incomplete 3:commits: 1/5; Missing valid saved PR base/head",
		"pr_details: 1 PR detail collections still pending",
	], "failures");
});

Deno.test("Tier B fetches only selected items and their threads", async () => {
	const plan: TierPlan = {
		repo: "fixture/project",
		tier: "B",
		selected_pr_numbers: [2],
		selected_issue_numbers: [4],
		policy_sha256: "h",
	};
	const result = await collect(plan);
	assertEquals(result.code, 0, "exit code");
	assertEquals(
		result.counts,
		{ issue: 1, issue_comment: 3, pr_commit: 101, pull: 1 },
		"records",
	);
	const listed = result.requests.filter((path) =>
		path.endsWith("/pulls") || path.endsWith("/issues")
	);
	assertEquals(listed, [], "repository-wide inventory requests");
});
