/**
 * Resumable enumeration of one GitHub search query. Each query's matched item
 * numbers and cursor are cached under a SHA-256 of the query text.
 */
import { join } from "@std/path";
import { readJsonIfExists, writeJsonAtomic } from "../lib/files.ts";
import type { SearchTransport } from "./search_transport.ts";

/** GitHub returns at most 1,000 results; the caller must narrow the query. */
export class SearchCap extends Error {}

/** Tokens can share a user quota, so searches are also spaced globally. */
const GLOBAL_SEARCH_GAP_MS = 2100;

type CachedQuery = {
	query: string;
	numbers: number[];
	cursor: string | null;
	done: boolean;
	total: number;
	started_at: string;
	updated_at?: string;
};

async function sha256Hex(text: string): Promise<string> {
	const bytes = new Uint8Array(
		await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)),
	);
	return Array.from(bytes).map((x) => x.toString(16).padStart(2, "0")).join("");
}

export class CachedSearch {
	private lastSearch = 0;

	constructor(
		private readonly cacheDir: string,
		private readonly transport: SearchTransport,
		private readonly check: () => void,
		private readonly searchGapMs = GLOBAL_SEARCH_GAP_MS,
	) {}

	/** All item numbers matching `query`; throws {@link SearchCap} above 1,000 results. */
	async matches(query: string): Promise<Set<number>> {
		this.check();
		const path = join(this.cacheDir, (await sha256Hex(query)) + ".json");
		const state = await readJsonIfExists<CachedQuery>(path) ?? {
			query,
			numbers: [],
			cursor: null,
			done: false,
			total: 0,
			started_at: new Date().toISOString(),
		};
		if (state.query !== query) throw new Error("Search cache mismatch");
		const found = new Set<number>(state.numbers);
		if (state.done) return found;
		while (true) {
			this.check();
			const wait = this.searchGapMs - (Date.now() - this.lastSearch);
			if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
			await this.transport.paceSearch();
			this.lastSearch = Date.now();
			this.check();
			const page = await this.transport.searchPage(query, state.cursor);
			if (page.issueCount > 1000) throw new SearchCap(query);
			if (!Array.isArray(page.nodes) || page.nodes.some((n) => !Number.isInteger(n?.number))) {
				throw new Error("Invalid search result");
			}
			for (const n of page.nodes) found.add(n.number);
			state.total = Math.max(state.total, page.issueCount);
			if (
				page.pageInfo.hasNextPage &&
				(!page.pageInfo.endCursor || page.pageInfo.endCursor === state.cursor)
			) throw new Error("Search cursor stalled");
			state.cursor = page.pageInfo.endCursor;
			state.numbers = [...found].sort((a, b) => a - b);
			state.updated_at = new Date().toISOString();
			state.done = !page.pageInfo.hasNextPage && found.size >= state.total;
			await writeJsonAtomic(path, state);
			if (!page.pageInfo.hasNextPage) {
				if (!state.done) {
					throw new Error(`Incomplete search enumeration ${found.size}/${state.total}`);
				}
				return found;
			}
		}
	}
}
