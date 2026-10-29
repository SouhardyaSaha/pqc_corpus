/**
 * Tier classification of one repository: score it from GitHub search, assign
 * its tier, and freeze the selected PR/issue numbers in a tier plan.
 */
import { join, resolve } from "@std/path";
import { readJsonIfExists, writeJsonAtomic } from "../lib/files.ts";
import type { RepositoryMetadata, SearchTransport } from "./search_transport.ts";
import { KeywordMatcher } from "./matching.ts";
import { assignTier } from "./policy.ts";
import { CachedSearch } from "./search_cache.ts";

export type TierSearchTarget = {
	run: string;
	repo: string;
	terms: string[];
	cutoff: number;
	policySha256: string;
	planPath: string;
	cacheDir: string;
};

type CachedMetadata = RepositoryMetadata & { fetched_at: string };

function requiredArg(args: string[], name: string): string {
	const value = args.find((x) => x.startsWith(`--${name}=`))?.slice(name.length + 3);
	if (!value) throw new Error(`--${name} is required`);
	return value;
}

/** Resolve the frozen manifest, policy, and per-repository output locations. */
export async function loadTarget(args: string[]): Promise<TierSearchTarget> {
	const run = resolve(requiredArg(args, "run-dir"));
	const repo = requiredArg(args, "repo");
	const manifest = JSON.parse(await Deno.readTextFile(join(run, "manifest.json")));
	const policy = JSON.parse(await Deno.readTextFile(join(run, "tier_policy.json")));
	if (!manifest.repositories.some((x: { repo: string }) => x.repo === repo)) {
		throw new Error("Repository outside frozen manifest");
	}
	const slug = repo.toLowerCase().replace("/", "__");
	return {
		run,
		repo,
		terms: policy.terms,
		cutoff: policy.cutoff,
		policySha256: manifest.tiering.policy_sha256,
		planPath: join(run, "tier_plans", slug + ".json"),
		cacheDir: join(run, "tier_search_cache", slug),
	};
}

async function cachedMetadata(
	target: TierSearchTarget,
	transport: SearchTransport,
): Promise<CachedMetadata> {
	const metaPath = join(target.cacheDir, "metadata.json");
	const saved = await readJsonIfExists<CachedMetadata>(metaPath);
	if (saved) return saved;
	const [owner, name] = target.repo.split("/");
	const repository = await transport.repositoryMetadata(owner, name);
	if (!repository) throw new Error("Repository unavailable");
	const meta = { ...repository, fetched_at: new Date().toISOString() };
	await writeJsonAtomic(metaPath, meta);
	return meta;
}

/**
 * Score the repository on any-text matches, assign its tier, and, for Tier B,
 * select the items whose title or body matches. An existing plan is reused.
 */
export async function classifyRepository(
	target: TierSearchTarget,
	transport: SearchTransport,
	check: () => void,
	searchGapMs?: number,
): Promise<void> {
	const existing = await readJsonIfExists<{ policy_sha256: string; tier: string }>(target.planPath);
	if (existing) {
		if (existing.policy_sha256 !== target.policySha256) throw new Error("Tier policy changed");
		console.log(`Reusing tier ${existing.tier}: ${target.repo}`);
		return;
	}
	const meta = await cachedMetadata(target, transport);
	const search = new CachedSearch(target.cacheDir, transport, check, searchGapMs);
	const matcher = new KeywordMatcher(search, target.repo, target.terms, check);
	const denominator = meta.pullRequests.totalCount + meta.issues.totalCount;
	const anyPrs = denominator ? await matcher.allMatches("pr", "any") : [];
	const anyIssues = denominator ? await matcher.allMatches("issue", "any") : [];
	const ratio = denominator ? (anyPrs.length + anyIssues.length) / denominator : null;
	const tier = assignTier(anyPrs.length + anyIssues.length, denominator, target.cutoff);
	const selectedPrs = tier === "B" ? await matcher.allMatches("pr", "title_body") : [];
	const selectedIssues = tier === "B" ? await matcher.allMatches("issue", "title_body") : [];
	await Deno.mkdir(join(target.run, "tier_plans"), { recursive: true });
	await writeJsonAtomic(target.planPath, {
		repo: target.repo,
		canonical_repo: meta.nameWithOwner,
		repo_id: String(meta.databaseId),
		tier,
		ratio,
		denominator,
		matched_prs: anyPrs.length,
		matched_issues: anyIssues.length,
		any_pr_numbers: anyPrs,
		any_issue_numbers: anyIssues,
		selected_pr_numbers: selectedPrs,
		selected_issue_numbers: selectedIssues,
		selection: tier === "B" ? "github_search_title_body" : "all",
		policy_sha256: target.policySha256,
		metadata: meta,
		completed_at: new Date().toISOString(),
	});
	console.log(
		`Tier ${tier}: ${target.repo}; ratio=${ratio}; selected PRs=${
			tier === "B" ? selectedPrs.length : "all"
		}`,
	);
}
