/** Request pacing: sleep only when a request would otherwise be throttled. */

import {
	chooseReadyToken,
	hasEnoughQuota,
	minGapMs,
	soonestToken,
	waitNeededForToken,
} from "./quota.ts";
import type { Resource } from "./rate_state.ts";
import { pool, switchToken, type TokenState } from "./tokens.ts";

export function sleep(ms: number): Promise<void> {
	return new Promise((r) => setTimeout(r, ms));
}

export function setMinimumRequestGap(resource: Resource, ms: number): void {
	if (!Number.isFinite(ms) || ms < 0) {
		throw new Error(`Minimum request gap for ${resource} must be a non-negative number.`);
	}
	minGapMs[resource] = ms;
}

/**
 * Wait until at least `count * minGapMs[r]` has passed since our last request
 * to this resource. `count` defaults to 1; pass a higher value when one HTTP
 * request consumes multiple slots (e.g. an aliased GraphQL search round
 * consumes one search-API slot per aliased query).
 */
export async function paceMinimumGapForToken(
	state: TokenState,
	r: Resource,
	count = 1,
): Promise<void> {
	const gapMs = minGapMs[r] * Math.max(1, count);
	if (gapMs <= 0) return;

	const now = Date.now();
	const elapsed = now - state.lastRequestAtMs[r];
	if (state.lastRequestAtMs[r] > 0 && elapsed < gapMs) {
		await sleep(gapMs - elapsed);
	}
	state.lastRequestAtMs[r] = Date.now();
}

/** After sleeping until a reset, treat the token's quota as unknown again. */
function refreshIfReset(state: TokenState, r: Resource): void {
	if (state.resources[r].resetAtMs <= Date.now()) {
		state.resources[r].remaining = Number.POSITIVE_INFINITY;
		state.cooldownUntilMs[r] = 0;
	}
}

async function paceResource(r: Resource, count = 1): Promise<void> {
	while (true) {
		const readyIndex = chooseReadyToken(r, count);
		if (readyIndex !== null) {
			switchToken(readyIndex, `${r} quota available`);
			await paceMinimumGapForToken(pool.states[readyIndex], r, count);
			return;
		}

		const { index, waitMs } = soonestToken(r, count);
		if (index === null || !Number.isFinite(waitMs)) {
			throw new Error("No usable GitHub token is available.");
		}

		switchToken(index, `${r} reset soonest`);
		const seconds = Math.ceil(waitMs / 1000);
		console.log(`  [pace] all tokens low/cooling for ${r}; waiting ${seconds}s`);
		await sleep(waitMs);
		refreshIfReset(pool.states[index], r);
	}
}

/** Select once for a GraphQL search, then pace both quotas on that token. */
export async function paceGraphqlSearch(searchCount = 1): Promise<void> {
	const resources: [Resource, number][] = [["search", searchCount], ["graphql", 1]];
	const total = pool.states.length;
	while (true) {
		const now = Date.now();
		let chosen: number | null = null;
		let bestWait = Infinity;
		let soonest: number | null = null;
		let soonestWait = Infinity;
		for (let offset = 0; offset < total; offset++) {
			const index = pool.strategy === "round-robin"
				? (pool.nextRoundRobin + offset) % total
				: offset;
			const state = pool.states[index];
			const wait = Math.max(
				...resources.map(([r, count]) => waitNeededForToken(state, r, count, now)),
			);
			if (wait < soonestWait) {
				soonest = index;
				soonestWait = wait;
			}
			if (!resources.every(([r, count]) => hasEnoughQuota(state, r, count, now))) continue;
			if (pool.strategy === "round-robin") {
				chosen = index;
				break;
			}
			if (wait < bestWait) {
				chosen = index;
				bestWait = wait;
			}
		}
		if (chosen !== null) {
			if (pool.strategy === "round-robin") pool.nextRoundRobin = (chosen + 1) % total;
			switchToken(chosen, "search + graphql quota available");
			for (const [r, count] of resources) {
				await paceMinimumGapForToken(pool.states[chosen], r, count);
			}
			return;
		}
		if (soonest === null || !Number.isFinite(soonestWait)) {
			throw new Error("No usable GitHub token is available.");
		}
		console.log(
			`  [pace] all tokens low/cooling for search + graphql; waiting ${
				Math.ceil(soonestWait / 1000)
			}s`,
		);
		await sleep(soonestWait);
		for (const [r] of resources) refreshIfReset(pool.states[soonest], r);
	}
}

export const paceCore = (count = 1) => paceResource("core", count);
export const paceGraphql = (count = 1) => paceResource("graphql", count);
export const paceSearch = (count = 1) => paceResource("search", count);
