import type { Progress } from "./store.ts";

export const detailStreams = ["commits", "closingIssuesReferences", "reviews"] as const;
export type DetailStream = typeof detailStreams[number];
export type Connection = {
	nodes: Array<Record<string, unknown>>;
	totalCount: number;
	pageInfo: { hasNextPage: boolean; endCursor: string | null };
};
export type PullPage = Partial<Record<DetailStream, Connection>>;
export type DetailRequest = {
	number: number;
	progress: Record<DetailStream, Progress>;
};
export type BatchQuery = { query: string; variables: Record<string, string | null> };
export type BatchResult = { repository: Record<string, PullPage | null> | null };
export type PageOutcome = { page: PullPage | null } | { error: unknown };

const fields: Record<DetailStream, string> = {
	commits: "commit { oid }",
	closingIssuesReferences: "id number url title repository {id nameWithOwner}",
	reviews: "id databaseId author {login} body state submittedAt url commit {oid}",
};

/** Each alias has independent cursors; completed connections are not fetched again. */
export function buildDetailBatch(requests: DetailRequest[]): BatchQuery {
	if (!requests.length || requests.length > 20) throw new Error("Expected 1–20 PRs per batch");
	const declarations = ["$owner:String!", "$name:String!"];
	const variables: Record<string, string | null> = {};
	const aliases: string[] = [];
	const seen = new Set<number>();
	for (const request of requests) {
		if (!Number.isSafeInteger(request.number) || request.number < 1 || seen.has(request.number)) {
			throw new Error("Invalid or duplicate PR number");
		}
		seen.add(request.number);
		const connections: string[] = [];
		for (const stream of detailStreams) {
			const progress = request.progress[stream];
			if (progress.done) continue;
			const variable = `c_${request.number}_${stream}`;
			declarations.push(`$${variable}:String`);
			variables[variable] = progress.cursor;
			connections.push(`${stream}(first:100,after:$${variable}) {
			 totalCount nodes { ${fields[stream]} } pageInfo {hasNextPage endCursor}
			}`);
		}
		if (!connections.length) throw new Error("Completed PR must not enter a batch");
		aliases.push(
			`pr_${request.number}:pullRequest(number:${request.number}) {${connections.join("\n")}}`,
		);
	}
	return {
		query: `query(${declarations.join(",")}) {repository(owner:$owner,name:$name) {${
			aliases.join("\n")
		}}}`,
		variables,
	};
}

/** Split unsuccessful queries so one unavailable PR cannot hide its neighbors. */
export async function fetchDetailBatch(
	requests: DetailRequest[],
	fetch: (query: BatchQuery) => Promise<BatchResult>,
	options: {
		check: () => void;
		canSplit: (error: unknown) => boolean;
		onSplit: (size: number, error: unknown) => void;
	},
): Promise<Map<number, PageOutcome>> {
	options.check();
	let result: BatchResult;
	try {
		result = await fetch(buildDetailBatch(requests));
	} catch (error) {
		options.check();
		if (requests.length > 1 && options.canSplit(error)) {
			options.onSplit(requests.length, error);
			const middle = Math.ceil(requests.length / 2);
			const left = await fetchDetailBatch(requests.slice(0, middle), fetch, options);
			const right = await fetchDetailBatch(requests.slice(middle), fetch, options);
			return new Map([...left, ...right]);
		}
		return new Map(requests.map(({ number }) => [number, { error }]));
	}
	return new Map(requests.map(({ number }) => [number, {
		page: result.repository?.[`pr_${number}`] ?? null,
	}]));
}
