/** Quota checks and token choice; no waiting happens here. */

import type { Resource } from "./rate_state.ts";
import { pool, type TokenState } from "./tokens.ts";

/** Minimum spacing between requests to one resource on one token. */
export const minGapMs: Record<Resource, number> = {
	core: 0,
	search: 2100,
	graphql: 0,
};

/** Number of remaining calls below which we wait for the window to reset. */
const SAFETY_FLOOR = {
	graphql: 50, // points
	search: 2, // calls
	core: 50, // requests
} as const;

export function hasEnoughQuota(
	state: TokenState,
	r: Resource,
	count: number,
	now: number,
): boolean {
	if (state.disabled) return false;
	if (state.cooldownUntilMs[r] > now) return false;

	const resource = state.resources[r];
	if (!Number.isFinite(resource.remaining)) return true; // unknown — try it.
	if (resource.resetAtMs > 0 && resource.resetAtMs <= now) return true;
	return resource.remaining - count > SAFETY_FLOOR[r];
}

export function waitNeededForToken(
	state: TokenState,
	r: Resource,
	count: number,
	now: number,
): number {
	if (state.disabled) return Number.POSITIVE_INFINITY;

	const gapMs = minGapMs[r] * Math.max(1, count);
	const gapWait = state.lastRequestAtMs[r] > 0
		? Math.max(0, state.lastRequestAtMs[r] + gapMs - now)
		: 0;
	const cooldownWait = Math.max(0, state.cooldownUntilMs[r] - now);
	const resource = state.resources[r];
	const quotaLow = Number.isFinite(resource.remaining) &&
		resource.remaining - count <= SAFETY_FLOOR[r];
	const quotaWait = quotaLow
		? resource.resetAtMs > now ? resource.resetAtMs - now + 500 : 60_000
		: 0;

	return Math.max(gapWait, cooldownWait, quotaWait);
}

function chooseRoundRobinReadyToken(r: Resource, count: number, now: number): number | null {
	const total = pool.states.length;
	for (let offset = 0; offset < total; offset++) {
		const index = (pool.nextRoundRobin + offset) % total;
		if (!hasEnoughQuota(pool.states[index], r, count, now)) continue;
		pool.nextRoundRobin = (index + 1) % total;
		return index;
	}
	return null;
}

/** Pick a token that can send now, honoring the configured strategy. */
export function chooseReadyToken(r: Resource, count: number, now = Date.now()): number | null {
	if (pool.strategy === "round-robin") return chooseRoundRobinReadyToken(r, count, now);

	let bestIndex: number | null = null;
	let bestWait = Number.POSITIVE_INFINITY;
	let bestScore = Number.NEGATIVE_INFINITY;
	for (const state of pool.states) {
		if (!hasEnoughQuota(state, r, count, now)) continue;
		const waitMs = waitNeededForToken(state, r, count, now);
		const remaining = state.resources[r].remaining;
		const score = Number.isFinite(remaining) ? remaining : Number.MAX_SAFE_INTEGER - state.index;
		if (
			waitMs < bestWait ||
			(waitMs === bestWait &&
				(state.index === pool.current ||
					(bestIndex !== pool.current && score > bestScore)))
		) {
			bestWait = waitMs;
			bestScore = score;
			bestIndex = state.index;
		}
	}
	return bestIndex;
}

/** The token that becomes usable first when none is ready now. */
export function soonestToken(r: Resource, count: number, now = Date.now()): {
	index: number | null;
	waitMs: number;
} {
	let bestIndex: number | null = null;
	let bestWait = Number.POSITIVE_INFINITY;
	for (const state of pool.states) {
		const waitMs = waitNeededForToken(state, r, count, now);
		if (waitMs < bestWait) {
			bestWait = waitMs;
			bestIndex = state.index;
		}
	}
	return { index: bestIndex, waitMs: bestWait };
}
