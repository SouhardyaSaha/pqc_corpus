/**
 * Keyword matching through GitHub search. Terms are OR-ed in chunks of six
 * (larger OR chains silently return nothing) and results are unioned by number.
 */
import { type CachedSearch, SearchCap } from "./search_cache.ts";

export type ItemKind = "pr" | "issue";
/** `any` scores the corpus (title, body, comments); `title_body` selects corpus B items. */
export type MatchScope = "any" | "title_body";
/** Creation-time interval in epoch milliseconds, inclusive. */
export type CreatedRange = [number, number];

const TERMS_PER_QUERY = 6;
const EARLIEST_CREATED = Date.parse("2008-01-01T00:00:00Z");

function searchTimestamp(ms: number): string {
	return new Date(ms).toISOString().replace(".000", "");
}

export function buildSearchQuery(
	repo: string,
	kind: ItemKind,
	scope: MatchScope,
	terms: string[],
	range?: CreatedRange,
): string {
	const words = terms.map((x) => `"${x}"`).join(" OR ");
	const date = range ? ` created:${searchTimestamp(range[0])}..${searchTimestamp(range[1])}` : "";
	const fields = scope === "title_body" ? " in:title,body" : " in:title,body,comments";
	return `repo:${repo} is:${kind}${fields} ${words}${date}`;
}

function union(sets: Set<number>[]): Set<number> {
	return new Set(sets.flatMap((x) => [...x]));
}

export class KeywordMatcher {
	constructor(
		private readonly search: CachedSearch,
		private readonly repo: string,
		private readonly terms: string[],
		private readonly check: () => void,
	) {}

	/** Sorted numbers of every item matching any policy term. */
	async allMatches(kind: ItemKind, scope: MatchScope): Promise<number[]> {
		const sets = [];
		for (let i = 0; i < this.terms.length; i += TERMS_PER_QUERY) {
			this.check();
			sets.push(await this.matching(kind, scope, this.terms.slice(i, i + TERMS_PER_QUERY)));
			console.log(
				`${this.repo} ${kind} ${scope} terms=${
					Math.min(i + TERMS_PER_QUERY, this.terms.length)
				}/${this.terms.length}`,
			);
		}
		return [...union(sets)].sort((a, b) => a - b);
	}

	/**
	 * Enumerate one chunk. Above GitHub's 1,000-result cap, split the terms, then
	 * the creation-time range, so the union still covers the whole interval.
	 */
	private async matching(
		kind: ItemKind,
		scope: MatchScope,
		terms: string[],
		range?: CreatedRange,
	): Promise<Set<number>> {
		try {
			return await this.search.matches(buildSearchQuery(this.repo, kind, scope, terms, range));
		} catch (error) {
			if (!(error instanceof SearchCap)) throw error;
			if (terms.length > 1) {
				const middle = Math.ceil(terms.length / 2);
				return union([
					await this.matching(kind, scope, terms.slice(0, middle), range),
					await this.matching(kind, scope, terms.slice(middle), range),
				]);
			}
			const [lo, hi] = range ?? [EARLIEST_CREATED, Math.floor(Date.now() / 1000) * 1000];
			if (hi - lo < 1000) {
				throw new Error("Search cap within one second; refusing incomplete selection");
			}
			const mid = Math.floor((lo + hi) / 2000) * 1000;
			return union([
				await this.matching(kind, scope, terms, [lo, mid]),
				await this.matching(kind, scope, terms, [mid + 1000, hi]),
			]);
		}
	}
}
