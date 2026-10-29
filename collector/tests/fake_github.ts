/** Canned GitHub responses for offline collector and corpus-search tests. */
import type { GitHubTransport, RestResponse } from "../api/session.ts";
import type {
	RepositoryMetadata,
	SearchPage,
	SearchTransport,
} from "../search/search_transport.ts";

const API = "https://api.github.com";
export const REPO = { id: 101, full_name: "fixture/project", has_issues: true };

const pull = (n: number) => ({ id: 1000 + n, number: n, title: `PR ${n}` });
const issue = (n: number, isPull = false) => ({
	id: 2000 + n,
	number: n,
	...(isPull ? { pull_request: {} } : {}),
});
const comment = (id: number, item: number) => ({
	id,
	issue_url: `${API}/repos/fixture/project/issues/${item}`,
});

/** Paged list endpoints, keyed by the path after the repository prefix. */
const LISTS: Record<string, unknown[][]> = {
	"/pulls": [[pull(1), pull(2)], [pull(3)]],
	"/issues": [[issue(1, true), issue(2, true), issue(3, true), issue(4)]],
	"/issues/comments": [[comment(1, 1)]],
	"/pulls/comments": [[]],
	"/issues/2/comments": [[comment(2, 2)], [comment(3, 2)]],
	"/issues/4/comments": [[comment(4, 4)]],
	"/pulls/2/comments": [[]],
};

type Connection = {
	totalCount: number;
	nodes: unknown[];
	pageInfo: { hasNextPage: boolean; endCursor: string | null };
};

const oid = (n: number) => n.toString(16).padStart(40, "0");

/** PR 2 needs a second commit page; PR 3 reports more commits than it returns. */
function commits(n: number, cursor: string | null): Connection {
	if (n === 2 && cursor !== "page2") {
		return {
			totalCount: 101,
			nodes: Array.from({ length: 100 }, (_, i) => ({ commit: { oid: oid(i) } })),
			pageInfo: { hasNextPage: true, endCursor: "page2" },
		};
	}
	if (n === 2) {
		return {
			totalCount: 101,
			nodes: [{ commit: { oid: oid(100) } }],
			pageInfo: { hasNextPage: false, endCursor: "end" },
		};
	}
	return {
		totalCount: n === 3 ? 5 : 1,
		nodes: [{ commit: { oid: oid(1000 + n) } }],
		pageInfo: { hasNextPage: false, endCursor: "end" },
	};
}

const empty = (): Connection => ({
	totalCount: 0,
	nodes: [],
	pageInfo: { hasNextPage: false, endCursor: null },
});

function detailPage(n: number, variables: Record<string, unknown>, prefix: string) {
	const page: Record<string, Connection> = {};
	if (`${prefix}commits` in variables) {
		page.commits = commits(n, variables[`${prefix}commits`] as string | null);
	}
	if (`${prefix}closingIssuesReferences` in variables) page.closingIssuesReferences = empty();
	if (`${prefix}reviews` in variables) page.reviews = empty();
	return page;
}

export class FakeGitHub implements GitHubTransport {
	readonly requests: string[] = [];

	tokenCount(): number {
		return 1;
	}

	describeRateState(): string {
		return "fake";
	}

	rest(path: string): Promise<RestResponse> {
		const url = new URL(path, API);
		this.requests.push(url.pathname);
		if (url.pathname === "/repos/fixture/project") {
			return Promise.resolve({ data: REPO, headers: {} });
		}
		const single = url.pathname.match(/^\/repos\/fixture\/project\/(pulls|issues)\/(\d+)$/);
		if (single) {
			const n = Number(single[2]);
			return Promise.resolve({ data: single[1] === "pulls" ? pull(n) : issue(n), headers: {} });
		}
		const suffix = url.pathname.replace(/^\/repos\/fixture\/project|^\/repositories\/101/, "");
		const pages = LISTS[suffix];
		if (!pages) return Promise.reject(Object.assign(new Error("Not Found"), { status: 404 }));
		const page = Number(url.searchParams.get("page") ?? 1);
		const headers: { link?: string } = {};
		if (page < pages.length) {
			const next = new URL(`${API}/repositories/101${suffix}`);
			url.searchParams.forEach((value, key) => next.searchParams.set(key, value));
			next.searchParams.set("page", String(page + 1));
			headers.link = `<${next.href}>; rel="next"`;
		}
		return Promise.resolve({ data: pages[page - 1] ?? [], headers });
	}

	graphql<T>(query: string, variables: Record<string, unknown>): Promise<T> {
		this.requests.push("graphql");
		if (query.includes("pullRequest(number:$number)")) {
			const n = Number(variables.number);
			const renamed = { commits: variables.cc, closingIssuesReferences: null, reviews: null };
			return Promise.resolve({
				repository: { pullRequest: detailPage(n, renamed, "") },
			} as T);
		}
		const repository: Record<string, unknown> = {};
		for (const match of query.matchAll(/pr_(\d+):pullRequest/g)) {
			const n = Number(match[1]);
			repository[`pr_${n}`] = detailPage(n, variables, `c_${n}_`);
		}
		return Promise.resolve({ repository } as T);
	}
}

/** Search results per term; any multi-term query containing "capped" exceeds the cap. */
export class FakeSearch implements SearchTransport {
	readonly queries: string[] = [];

	constructor(
		private readonly matches: Record<string, number[]>,
		private readonly totals = { pullRequests: 40, issues: 60 },
	) {}

	paceSearch(): Promise<void> {
		return Promise.resolve();
	}

	searchPage(query: string, _cursor: string | null): Promise<SearchPage> {
		this.queries.push(query);
		const terms = [...query.matchAll(/"([^"]+)"/g)].map((match) => match[1]);
		const wantPulls = query.includes(" is:pr ");
		const numbers = [...new Set(terms.flatMap((term) => this.matches[term] ?? []))]
			.filter((n) => (n < 100) === wantPulls)
			.sort((a, b) => a - b);
		const capped = terms.length > 1 && terms.includes("capped");
		return Promise.resolve({
			issueCount: capped ? 1001 : numbers.length,
			nodes: numbers.map((number) => ({ number })),
			pageInfo: { hasNextPage: false, endCursor: null },
		});
	}

	repositoryMetadata(): Promise<RepositoryMetadata> {
		return Promise.resolve({
			databaseId: 101,
			nameWithOwner: "fixture/project",
			createdAt: "2020-01-01T00:00:00Z",
			pullRequests: { totalCount: this.totals.pullRequests },
			issues: { totalCount: this.totals.issues },
		});
	}
}
