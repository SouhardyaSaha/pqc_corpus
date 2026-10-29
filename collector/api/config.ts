/** Command-line options, frozen manifest, and corpus plan for one collector run. */
import { join, resolve } from "@std/path";

/**
 * File names and keys inside a run directory. They are the format the frozen run was
 * collected with, which predates the word "corpus", so they keep the word "tier".
 */
export const RUN_FILES = {
	policy: "tier_policy.json",
	plans: "tier_plans",
	searchCache: "tier_search_cache",
} as const;

/** A repository's corpus as a plan stores it; "unrated" is corpus C (no PRs or issues). */
export type PlanCorpus = "A" | "B" | "unrated";

export type CorpusPlan = {
	repo: string;
	tier: PlanCorpus;
	selected_pr_numbers: number[];
	selected_issue_numbers: number[];
	policy_sha256: string;
};

export type Manifest = {
	repositories: Array<{ repo: string }>;
	/** Present in a run with corpus plans; holds the frozen policy's SHA-256. */
	tiering?: { policy_sha256: string };
};

export type CollectorOptions = {
	run: string;
	batchSize: number;
	onlyRepo?: string;
};

export function parseCollectorArgs(args: string[]): CollectorOptions {
	const argument = args.find((arg) => arg.startsWith("--run-dir="));
	if (!argument) throw new Error("--run-dir=PATH is required");
	const batchSize = Number(
		args.find((arg) => arg.startsWith("--pr-batch-size="))?.split("=")[1] ?? 10,
	);
	if (!Number.isInteger(batchSize) || batchSize < 1 || batchSize > 20) {
		throw new Error("--pr-batch-size must be an integer from 1 to 20");
	}
	return {
		run: resolve(argument.slice("--run-dir=".length)),
		batchSize,
		onlyRepo: args.find((arg) => arg.startsWith("--only-repo="))?.slice("--only-repo=".length),
	};
}

/** Read the frozen repository list, optionally narrowed to one listed repository. */
export async function loadManifest(run: string, onlyRepo?: string): Promise<Manifest> {
	const manifest = JSON.parse(await Deno.readTextFile(join(run, "manifest.json"))) as Manifest;
	if (onlyRepo) {
		manifest.repositories = manifest.repositories.filter((entry) =>
			entry.repo.toLowerCase() === onlyRepo.toLowerCase()
		);
		if (manifest.repositories.length !== 1) throw new Error("Repository not in frozen manifest");
	}
	return manifest;
}

/**
 * Load the frozen corpus plan of one repository. Raw runs have no plans. A run with
 * plans is collected one repository at a time by the Python pipeline.
 */
export async function loadCorpusPlan(
	run: string,
	manifest: Manifest,
	onlyRepo?: string,
): Promise<CorpusPlan | undefined> {
	if (!manifest.tiering) return undefined;
	if (!onlyRepo) {
		throw new Error(
			"A run with corpus plans is collected per repository (--only-repo); use `python -m pqc_corpus`",
		);
	}
	const plan = JSON.parse(
		await Deno.readTextFile(
			join(run, RUN_FILES.plans, onlyRepo.toLowerCase().replace("/", "__") + ".json"),
		),
	) as CorpusPlan | undefined;
	if (
		!plan || plan.policy_sha256 !== manifest.tiering.policy_sha256 ||
		plan.repo.toLowerCase() !== onlyRepo.toLowerCase() ||
		!["A", "B", "unrated"].includes(plan.tier)
	) throw new Error("Invalid or mismatched corpus plan");
	return plan;
}
