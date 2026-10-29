/**
 * PR/issue inventory and discussion threads.
 *
 * Raw runs page through repository-wide list endpoints. Tiered runs fetch only
 * the items frozen in the tier plan, and every thread of each selected item.
 */
import type { TierPlan } from "./config.ts";
import { collectListing } from "./listing.ts";
import type { CollectorSession, Repository } from "./session.ts";
import type { MiningStore } from "./store.ts";

const CREATED_ASCENDING = { sort: "created", direction: "asc" };

/** Raw run: every PR and issue in any state. */
export async function collectFullInventory(
	session: CollectorSession,
	repo: Repository,
): Promise<void> {
	const prefix = `/repos/${repo.full_name}`;
	await collectListing(session, repo, "pulls", prefix + "/pulls", "pull", {
		state: "all",
		...CREATED_ASCENDING,
	});
	// GitHub disables the issues endpoint for some mirrors/forks. Record that explicitly.
	if (repo.has_issues === false) {
		session.store.page(String(repo.id), "issues_disabled", [], { cursor: null, done: true });
	} else {
		await collectListing(session, repo, "issues", prefix + "/issues", "issue", {
			state: "all",
			...CREATED_ASCENDING,
		});
	}
}

/** Raw run: repository-wide general and inline review comment streams. */
export async function collectRepositoryDiscussions(
	session: CollectorSession,
	repo: Repository,
): Promise<void> {
	const prefix = `/repos/${repo.full_name}`;
	await collectListing(
		session,
		repo,
		"issue_comments",
		prefix + "/issues/comments",
		"issue_comment",
		CREATED_ASCENDING,
	);
	await collectListing(
		session,
		repo,
		"review_comments",
		prefix + "/pulls/comments",
		"review_comment",
		CREATED_ASCENDING,
	);
}

/** Tiered run: fetch each selected PR and issue that is not already saved. */
export async function collectSelectedInventory(
	session: CollectorSession,
	repo: Repository,
	plan: TierPlan,
): Promise<void> {
	const id = String(repo.id);
	const prefix = `/repos/${repo.full_name}`;
	for (
		const [kind, numbers, stream, path] of [
			["pull", plan.selected_pr_numbers, "pulls", "pulls"],
			["issue", plan.selected_issue_numbers, "issues", "issues"],
		] as const
	) {
		for (const number of numbers) {
			session.check();
			if (session.store.hasItem(id, kind, number)) continue;
			await session.report({
				stage: "selected_inventory",
				pr: kind === "pull" ? number : null,
				item: number,
			});
			const response = await session.rest(`${prefix}/${path}/${number}`);
			const data = response.data as Record<string, unknown>;
			if (!data.id || data.number !== number || (kind === "issue" && data.pull_request)) {
				throw new Error("Unexpected selected inventory object");
			}
			session.store.page(id, `selected:${kind}:${number}`, [{ kind, key: String(data.id), data }], {
				cursor: null,
				done: true,
			});
		}
		session.store.page(id, stream, [], { cursor: null, done: true });
	}
}

/**
 * Tiered run: fetch every comment thread of each selected item. Individual
 * threads are refetched instead of trusting repository-wide completion flags.
 */
export async function collectSelectedDiscussions(
	session: CollectorSession,
	repo: Repository,
	plan: TierPlan,
): Promise<void> {
	const prefix = `/repos/${repo.full_name}`;
	for (const number of [...plan.selected_pr_numbers, ...plan.selected_issue_numbers]) {
		await collectListing(
			session,
			repo,
			`item:${number}:issue_comments`,
			`${prefix}/issues/${number}/comments`,
			"issue_comment",
			{},
		);
	}
	for (const number of plan.selected_pr_numbers) {
		await collectListing(
			session,
			repo,
			`item:${number}:review_comments`,
			`${prefix}/pulls/${number}/comments`,
			"review_comment",
			{},
		);
	}
}

/** Tier A selects every saved PR and issue; other tiers use the frozen selection. */
export function discussionPlan(store: MiningStore, repoId: string, plan: TierPlan): TierPlan {
	if (plan.tier !== "A") return plan;
	return {
		...plan,
		selected_pr_numbers: store.itemNumbers(repoId, "pull"),
		selected_issue_numbers: store.itemNumbers(repoId, "issue"),
	};
}
