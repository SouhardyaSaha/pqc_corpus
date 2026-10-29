/** Resumable REST list pagination, one transaction per page. */
import { nextPage, resumePage } from "./pagination.ts";
import type { CollectorSession, Repository } from "./session.ts";
import type { StoredRecord } from "./store.ts";

/**
 * Save every page of a REST list endpoint under `stream`. GitHub's issue list
 * also returns PRs; those rows are stored as `pr_issue`, never as issues.
 */
export async function collectListing(
	session: CollectorSession,
	repo: Repository,
	stream: string,
	path: string,
	kind: string,
	params: Record<string, unknown> = {},
): Promise<void> {
	const id = String(repo.id);
	let progress = session.store.getProgress(id, stream);
	let url = resumePage(progress.cursor, path, id, params);
	while (!progress.done) {
		const page = new URL(url).searchParams.get("page");
		await session.report({ status: "running", repo: repo.full_name, stage: stream, page });
		const response = await session.rest(url);
		if (!Array.isArray(response.data)) throw new Error(`${stream}: expected a list`);
		const rows = response.data.map((data: Record<string, unknown>) =>
			listedRecord(stream, kind, data)
		);
		const next = nextPage(response.headers.link, path, id);
		if (next === url) throw new Error(`${stream}: pagination stalled`);
		if (next && !rows.length) throw new Error(`${stream}: empty page with next link`);
		progress = { cursor: next, done: !next };
		if (next) url = next;
		session.store.page(id, stream, rows, progress);
		console.log(
			`${repo.full_name} ${stream} page=${page} rows=${rows.length} done=${progress.done} ${session.describeRateState()}`,
		);
	}
}

function listedRecord(stream: string, kind: string, data: Record<string, unknown>): StoredRecord {
	if (data.id === undefined) throw new Error(`${stream}: missing GitHub object ID`);
	return {
		kind: kind === "issue" && data.pull_request ? "pr_issue" : kind,
		key: String(data.id),
		data,
	};
}
