/**
 * Breadth-first collection: all repository inventories, then discussions, then
 * PR details. Each phase gets up to three passes; failures stay recorded.
 */
import { safeErrorMessage } from "../lib/errors.ts";
import type { CorpusPlan, Manifest } from "./config.ts";
import {
	collectFullInventory,
	collectRepositoryDiscussions,
	collectSelectedDiscussions,
	collectSelectedInventory,
	discussionPlan,
} from "./items.ts";
import { collectPullRequestDetails } from "./pull_details.ts";
import { type CollectorSession, Paused, type Repository } from "./session.ts";

export const PHASES = ["inventory", "discussions", "pr_details"] as const;
export type Phase = typeof PHASES[number];

const PASSES_PER_PHASE = 3;

/** Run every phase for every manifest repository. Returns the process exit code. */
export async function collectPhases(
	session: CollectorSession,
	manifest: Manifest,
	corpusPlan: CorpusPlan | undefined,
	batchSize: number,
): Promise<number> {
	console.log(
		`Repository mining: ${manifest.repositories.length} repositories; ${session.transport.tokenCount()} configured tokens; PR batch size ${batchSize}`,
	);
	for (const phase of PHASES) {
		for (let attempt = 0; attempt < PASSES_PER_PHASE; attempt++) {
			for (let index = 0; index < manifest.repositories.length; index++) {
				session.check();
				const requested = manifest.repositories[index].repo;
				const saved = session.store.lookup(requested);
				if (saved && session.store.getProgress(String(saved.id), `phase:${phase}`).done) continue;
				try {
					await session.report({
						status: "running",
						phase,
						stage: "repository",
						repo: requested,
						repository_index: index + 1,
						repositories: manifest.repositories.length,
						attempt: attempt + 1,
					});
					const repo = saved ?? await fetchRepository(session, requested);
					await collectPhase(session, phase, requested, repo, corpusPlan, batchSize);
					session.store.page(String(repo.id), `phase:${phase}`, [], { cursor: null, done: true });
					session.store.clearFailure(requested, phase);
				} catch (error) {
					if (error instanceof Paused) throw error;
					session.store.failure(requested, phase, safeErrorMessage(error));
					console.error(`${requested} ${phase}: deferred (${safeErrorMessage(error)})`);
				}
			}
		}
	}
	return await reportCompletion(session);
}

/** Save the repository identity and its requested-name alias. */
async function fetchRepository(session: CollectorSession, requested: string): Promise<Repository> {
	const result = await session.rest(`/repos/${requested}`);
	const repo = result.data as Repository;
	if (!repo.id || !repo.full_name) throw new Error("Invalid repository response");
	session.store.repository(requested, repo);
	return repo;
}

async function collectPhase(
	session: CollectorSession,
	phase: Phase,
	requested: string,
	repo: Repository,
	corpusPlan: CorpusPlan | undefined,
	batchSize: number,
): Promise<void> {
	if (phase === "inventory") {
		if (corpusPlan && corpusPlan.tier !== "A") {
			await collectSelectedInventory(session, repo, corpusPlan);
		} else {
			await collectFullInventory(session, repo);
		}
	} else if (phase === "discussions") {
		if (corpusPlan) {
			const plan = discussionPlan(session.store, String(repo.id), corpusPlan);
			await collectSelectedDiscussions(session, repo, plan);
		} else {
			await collectRepositoryDiscussions(session, repo);
		}
	} else {
		await collectPullRequestDetails(session, repo, requested, batchSize);
	}
}

async function reportCompletion(session: CollectorSession): Promise<number> {
	const failures = session.store.failures();
	const counts = session.store.recordCounts();
	await session.report({
		status: failures.length ? "completed_with_gaps" : "completed",
		counts,
		failures,
	});
	console.log(JSON.stringify({ counts, failures }));
	return failures.length ? 2 : 0;
}
