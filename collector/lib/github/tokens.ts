/**
 * Configured GitHub token pool and the currently selected token.
 *
 * Reads `GITHUB_TOKEN_1..GITHUB_TOKEN_10` from the project `.env` (or the process
 * environment) when first imported. Token values are never logged.
 */

import { load } from "@std/dotenv";
import { join } from "@std/path";
import { Octokit } from "octokit";
import { PROJECT_ROOT } from "../paths.ts";
import {
	formatResourceState,
	initialResourceStates,
	type QuotaState,
	updateFromHeaders,
	zeroTimes,
} from "./rate_state.ts";

try {
	await load({ envPath: join(PROJECT_ROOT, ".env"), export: true });
} catch (_err) {
	/* no .env file — fine, we'll read from the process environment */
}

export type TokenStrategy = "smart" | "round-robin";

export interface TokenState extends QuotaState {
	index: number;
	client: Octokit;
}

interface TokenPool {
	states: TokenState[];
	strategy: TokenStrategy;
	/** Index of the token used for the next request. */
	current: number;
	/** Where the round-robin strategy starts its next search. */
	nextRoundRobin: number;
}

function loadTokens(): string[] {
	const tokens: string[] = [];
	for (let i = 1; i <= 10; i++) {
		const t = Deno.env.get(`GITHUB_TOKEN_${i}`);
		if (t) tokens.push(t);
	}
	if (tokens.length === 0) {
		throw new Error("No GitHub tokens found. Set GITHUB_TOKEN_1 in the project .env file.");
	}
	return tokens;
}

function loadTokenStrategy(): TokenStrategy {
	const value = (Deno.env.get("GITHUB_TOKEN_STRATEGY") ?? "round-robin").trim().toLowerCase();
	if (value === "smart" || value === "round-robin") return value;
	throw new Error("GITHUB_TOKEN_STRATEGY must be either 'smart' or 'round-robin'.");
}

/** Build a client whose responses update the quota state of its own token. */
function createTokenState(token: string, index: number): TokenState {
	const client = new Octokit({ auth: token });
	const state: TokenState = {
		index,
		client,
		resources: initialResourceStates(),
		lastRequestAtMs: zeroTimes(),
		cooldownUntilMs: zeroTimes(),
		disabled: false,
	};
	// `hook.after("request", ...)` fires for both REST and GraphQL responses.
	client.hook.after("request", (response, options) => {
		const url = (options.url ?? options.method ?? "") as string;
		updateFromHeaders(state, url, response.headers);
	});
	return state;
}

export const pool: TokenPool = {
	states: loadTokens().map(createTokenState),
	strategy: loadTokenStrategy(),
	current: 0,
	nextRoundRobin: 0,
};

export function getOctokit(): Octokit {
	return pool.states[pool.current].client;
}

export function tokenCount(): number {
	return pool.states.length;
}

export function switchToken(index: number, reason: string): boolean {
	if (index === pool.current) return true;
	pool.current = index;
	console.log(`  [token] using GITHUB_TOKEN_${pool.current + 1} (${reason})`);
	return true;
}

export function rotateToken(reason = "rotation"): boolean {
	if (pool.states.length <= 1) return false;
	for (let offset = 1; offset < pool.states.length; offset++) {
		const index = (pool.current + offset) % pool.states.length;
		if (!pool.states[index].disabled) return switchToken(index, reason);
	}
	return false;
}

export function disableCurrentToken(reason: string): void {
	const state = pool.states[pool.current];
	state.disabled = true;
	state.cooldownUntilMs.core = Number.POSITIVE_INFINITY;
	state.cooldownUntilMs.search = Number.POSITIVE_INFINITY;
	state.cooldownUntilMs.graphql = Number.POSITIVE_INFINITY;
	console.log(`  [token] disabled GITHUB_TOKEN_${pool.current + 1} (${reason})`);
}

export function describeRateState(): string {
	const current = pool.states[pool.current];
	return [
		`token=${pool.current + 1}/${pool.states.length}`,
		`strategy=${pool.strategy}`,
		formatResourceState("graphql", current.resources.graphql),
		formatResourceState("search", current.resources.search),
		formatResourceState("core", current.resources.core),
	].join("  ");
}
