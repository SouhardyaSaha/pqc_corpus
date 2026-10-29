/**
 * Per-PR GraphQL connections: commit links, closing-issue links, and reviews.
 *
 * Each connection keeps its own cursor. A connection is complete only when the
 * saved count matches GitHub's reported total; truncated commit lists are
 * reconstructed from Git and validated, never silently accepted.
 */
import { safeErrorMessage } from "../lib/errors.ts";
import {
	type BatchResult,
	type Connection,
	type DetailRequest,
	type DetailStream,
	detailStreams,
	fetchDetailBatch,
	type PullPage,
} from "./detail_batch.ts";
import { recoverCommits } from "./recovery.ts";
import { type CollectorSession, Paused, type Repository } from "./session.ts";
import type { MiningStore, Progress, StoredRecord } from "./store.ts";

type PullDetail = { repository: { pullRequest: PullPage | null } | null };

const PULL_DETAIL_QUERY =
	`query($owner:String!,$name:String!,$number:Int!,$cc:String,$ic:String,$rc:String) {
	 repository(owner:$owner,name:$name) { pullRequest(number:$number) {
	 commits(first:100,after:$cc) { totalCount nodes { commit { oid } } pageInfo {hasNextPage endCursor} }
	 closingIssuesReferences(first:100,after:$ic) {totalCount nodes {id number url title repository {id nameWithOwner}} pageInfo {hasNextPage endCursor}}
	 reviews(first:100,after:$rc) {totalCount nodes {id databaseId author {login} body state submittedAt url commit {oid}} pageInfo {hasNextPage endCursor}}
	 } } }`;

const RECORD_KIND: Record<DetailStream, string> = {
	commits: "pr_commit",
	closingIssuesReferences: "closing_issue_link",
	reviews: "review",
};

/** Batched queries fail fast so that one unavailable PR can be isolated by splitting. */
const BATCH_RETRY = { maxAttempts: 3, retryServerErrors: false };

/** A commit connection that ended with fewer saved links than GitHub reported. */
type CommitShortfall = { expected: number; collected: number };

/** Collect detail connections for every saved PR, in batches, recording per-PR gaps. */
export async function collectPullRequestDetails(
	session: CollectorSession,
	repo: Repository,
	requested: string,
	batchSize: number,
): Promise<void> {
	const id = String(repo.id);
	if (!session.store.getProgress(id, "pulls").done) {
		throw new Error("PR inventory is incomplete; defer details until it finishes");
	}
	const pending = pendingDetailRequests(session, id, requested);
	let gaps = 0;
	for (let offset = 0; offset < pending.length; offset += batchSize) {
		gaps += await collectDetailBatch(
			session,
			repo,
			requested,
			pending.slice(offset, offset + batchSize),
		);
	}
	if (gaps) throw new Error(`${gaps} PR detail collections still pending`);
}

/** PRs with at least one unfinished connection; clears failures of completed PRs. */
function pendingDetailRequests(
	session: CollectorSession,
	repoId: string,
	requested: string,
): DetailRequest[] {
	const pending: DetailRequest[] = [];
	for (const number of session.store.pullNumbersAscending(repoId)) {
		session.check();
		const progress = Object.fromEntries(detailStreams.map((stream) => [
			stream,
			session.store.getProgress(repoId, `pr:${number}:${stream}`),
		])) as DetailRequest["progress"];
		if (detailStreams.every((stream) => progress[stream].done)) {
			session.store.clearFailure(requested, `pr:${number}`);
		} else pending.push({ number, progress });
	}
	return pending;
}

/** Fetch one batch, then save each PR independently. Returns the number of failed PRs. */
async function collectDetailBatch(
	session: CollectorSession,
	repo: Repository,
	requested: string,
	batch: DetailRequest[],
): Promise<number> {
	await session.report({
		stage: "pr_details",
		page: null,
		pr: batch[0].number,
		batch_prs: batch.map((p) => p.number),
	});
	const began = Date.now();
	const [owner, name] = String(repo.full_name).split("/");
	const pages = await fetchDetailBatch(
		batch,
		({ query, variables }) =>
			session.graphql<BatchResult>(query, { owner, name, ...variables }, BATCH_RETRY),
		{
			check: () => session.check(),
			canSplit: canSplitBatch,
			onSplit: (size, error) =>
				console.warn(`Splitting ${size}-PR query: ${safeErrorMessage(error)}`),
		},
	);
	let gaps = 0;
	for (const { number } of batch) {
		session.check();
		try {
			const outcome = pages.get(number)!;
			if ("error" in outcome) throw outcome.error;
			await collectPullDetail(session, repo, number, outcome.page);
			session.store.clearFailure(requested, `pr:${number}`);
		} catch (error) {
			if (error instanceof Paused) throw error;
			gaps++;
			session.store.failure(requested, `pr:${number}`, safeErrorMessage(error));
			console.error(`${requested} pr=${number}: deferred (${safeErrorMessage(error)})`);
		}
	}
	console.log(
		`${repo.full_name} batch=${batch.length} elapsed_ms=${
			Date.now() - began
		} ${session.describeRateState()}`,
	);
	return gaps;
}

/** Quota and authentication failures would fail again in a smaller query. */
function canSplitBatch(error: unknown): boolean {
	const status = (error as { status?: number })?.status;
	return ![401, 403, 429].includes(status ?? 0) &&
		!/rate limit|quota|bad credentials/i.test(safeErrorMessage(error));
}

/**
 * Save one PR's connections until all are complete. A prefetched batch page is
 * used first; any further pages are requested for this PR alone.
 */
export async function collectPullDetail(
	session: CollectorSession,
	repo: Repository,
	number: number,
	prefetched?: PullPage | null,
): Promise<void> {
	const id = String(repo.id);
	const [owner, name] = String(repo.full_name).split("/");
	while (true) {
		const progress = detailStreams.map((key) =>
			session.store.getProgress(id, `pr:${number}:${key}`)
		);
		if (progress.every((p) => p.done)) return;
		await session.report({
			status: "running",
			repo: repo.full_name,
			stage: "pr_details",
			pr: number,
		});
		let pull: PullPage | null | undefined;
		if (prefetched !== undefined) {
			pull = prefetched;
			prefetched = undefined;
		} else {
			pull = await fetchPullPage(session, owner, name, number, progress);
		}
		if (!pull) throw new Error(`PR ${number} unavailable`);
		let shortfall: CommitShortfall | undefined;
		for (let i = 0; i < detailStreams.length; i++) {
			if (progress[i].done) continue;
			const key = detailStreams[i];
			shortfall = saveConnectionPage(session.store, id, number, key, pull[key], progress[i]) ??
				shortfall;
		}
		if (shortfall) await recoverShortfall(session, repo, number, shortfall);
		console.log(`${repo.full_name} pr=${number} details saved ${session.describeRateState()}`);
	}
}

async function fetchPullPage(
	session: CollectorSession,
	owner: string,
	name: string,
	number: number,
	progress: Progress[],
): Promise<PullPage | null | undefined> {
	const result = await session.graphql<PullDetail>(PULL_DETAIL_QUERY, {
		owner,
		name,
		number,
		cc: progress[0].done ? null : progress[0].cursor,
		ic: progress[1].done ? null : progress[1].cursor,
		rc: progress[2].done ? null : progress[2].cursor,
	});
	return result.repository?.pullRequest;
}

/**
 * Save one connection page with its cursor, then mark it complete only if the
 * saved count reaches GitHub's total. A commit shortfall is returned for Git
 * recovery; any other shortfall is an error.
 */
function saveConnectionPage(
	store: MiningStore,
	repoId: string,
	number: number,
	key: DetailStream,
	connection: Connection | undefined,
	progress: Progress,
): CommitShortfall | undefined {
	if (!connection || !Array.isArray(connection.nodes)) {
		throw new Error(`Missing ${key} connection`);
	}
	if (
		connection.pageInfo.hasNextPage &&
		(!connection.pageInfo.endCursor || connection.pageInfo.endCursor === progress.cursor)
	) {
		throw new Error(`Pagination stalled for ${number}:${key}`);
	}
	const kind = RECORD_KIND[key];
	const stream = `pr:${number}:${key}`;
	const rows = connection.nodes.map((node): StoredRecord => {
		const nodeKey = key === "commits" ? (node.commit as { oid: string }).oid : String(node.id);
		return { kind, key: `${number}:${nodeKey}`, data: { pr_number: number, ...node } };
	});
	store.page(repoId, stream, rows, { cursor: connection.pageInfo.endCursor, done: false });
	if (connection.pageInfo.hasNextPage) return undefined;
	const counted = store.countPullRecords(repoId, kind, number);
	if (counted >= connection.totalCount) {
		store.page(repoId, stream, [], { cursor: null, done: true });
		return undefined;
	}
	// Do not hide a discrepancy behind a successful checkpoint.
	store.resetProgress(repoId, stream);
	if (key !== "commits") {
		throw new Error(`Incomplete ${number}:${key}: ${counted}/${connection.totalCount}`);
	}
	return { expected: connection.totalCount, collected: counted };
}

/** GraphQL truncates some commit connections; rebuild them from the saved Git range. */
async function recoverShortfall(
	session: CollectorSession,
	repo: Repository,
	number: number,
	shortfall: CommitShortfall,
): Promise<void> {
	try {
		await recoverCommits(session.store, session.run, repo, number, shortfall.expected);
	} catch (error) {
		throw new Error(
			`Incomplete ${number}:commits: ${shortfall.collected}/${shortfall.expected}; ${
				safeErrorMessage(error)
			}`,
		);
	}
}
