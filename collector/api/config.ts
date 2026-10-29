/** Command-line options, frozen manifest, and tier plan for one collector run. */
import { join, resolve } from "@std/path";

export type Tier = "A" | "B" | "unrated";

export type TierPlan = {
	repo: string;
	tier: Tier;
	selected_pr_numbers: number[];
	selected_issue_numbers: number[];
	policy_sha256: string;
};

export type Manifest = {
	repositories: Array<{ repo: string }>;
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
 * Load the frozen tier plan for a tiered run. Raw runs have no plan. A tiered
 * run is collected one repository at a time by the tier pipeline.
 */
export async function loadTierPlan(
	run: string,
	manifest: Manifest,
	onlyRepo?: string,
): Promise<TierPlan | undefined> {
	if (!manifest.tiering) return undefined;
	if (!onlyRepo) {
		throw new Error(
			"Tiered collection requires --only-repo; use tier_pipeline.py for the complete corpus",
		);
	}
	const plan = JSON.parse(
		await Deno.readTextFile(
			join(run, "tier_plans", onlyRepo.toLowerCase().replace("/", "__") + ".json"),
		),
	) as TierPlan | undefined;
	if (
		!plan || plan.policy_sha256 !== manifest.tiering.policy_sha256 ||
		plan.repo.toLowerCase() !== onlyRepo.toLowerCase() ||
		!["A", "B", "unrated"].includes(plan.tier)
	) throw new Error("Invalid or mismatched tier plan");
	return plan;
}
