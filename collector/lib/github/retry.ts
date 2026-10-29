/** Rate-limit-aware retries with token fallback. */

import type { Octokit } from "octokit";
import { paceMinimumGapForToken, sleep } from "./pacing.ts";
import { chooseReadyToken, soonestToken } from "./quota.ts";
import { classifyResource, type Resource } from "./rate_state.ts";
import { disableCurrentToken, getOctokit, pool, rotateToken, switchToken } from "./tokens.ts";

interface OctokitErrorShape {
	status?: number;
	message?: string;
	response?: { headers?: Record<string, string>; url?: string };
}

export interface RetryOptions {
	maxAttempts?: number;
	retryServerErrors?: boolean;
}

function isRateLimitError(err: unknown): boolean {
	if (!err || typeof err !== "object") return false;
	const e = err as OctokitErrorShape;
	const msg = (e.message ?? "").toLowerCase();
	return (
		e.status === 403 ||
		e.status === 429 ||
		msg.includes("rate limit") ||
		msg.includes("secondary rate") ||
		msg.includes("quota")
	);
}

function isAuthError(err: unknown): boolean {
	if (!err || typeof err !== "object") return false;
	const e = err as OctokitErrorShape;
	const msg = (e.message ?? "").toLowerCase();
	return e.status === 401 || msg.includes("bad credentials");
}

function resourceFromError(err: unknown): Resource {
	if (err && typeof err === "object") {
		const e = err as OctokitErrorShape;
		const headers = e.response?.headers ?? {};
		const resource = headers["x-ratelimit-resource"] ?? headers["X-RateLimit-Resource"];
		return classifyResource(e.response?.url ?? "", resource);
	}
	return "core";
}

function isTransientServerError(err: unknown): boolean {
	if (!err || typeof err !== "object") return false;
	const e = err as OctokitErrorShape;
	return e.status !== undefined && e.status >= 500 && e.status < 600;
}

/**
 * Compute how long to wait before retrying after a rate-limit error.
 * Order of preference:
 *   1. `Retry-After` header (secondary rate limit — given in seconds)
 *   2. `X-RateLimit-Reset` header (primary — given as epoch seconds)
 *   3. Exponential backoff (1s → 4s → 16s → 60s).
 */
function retryDelayFromError(err: unknown, attempt: number): number {
	if (err && typeof err === "object") {
		const headers = (err as OctokitErrorShape).response?.headers ?? {};
		const retryAfter = headers["retry-after"] ?? headers["Retry-After"];
		if (retryAfter) {
			const n = Number(retryAfter);
			if (Number.isFinite(n) && n > 0) return Math.min(n * 1000 + 1000, 600_000);
		}
		const reset = headers["x-ratelimit-reset"] ?? headers["X-RateLimit-Reset"];
		if (reset) {
			const ms = Number(reset) * 1000 - Date.now() + 1000;
			if (ms > 0) return Math.min(ms, 600_000);
		}
	}
	return Math.min(60_000, 1000 * 4 ** attempt);
}

function markTokenRateLimited(
	tokenIndex: number,
	r: Resource,
	err: unknown,
	attempt: number,
): number {
	const waitMs = retryDelayFromError(err, attempt);
	const state = pool.states[tokenIndex];
	state.resources[r].remaining = 0;
	state.cooldownUntilMs[r] = Math.max(state.cooldownUntilMs[r], Date.now() + waitMs);

	if (err && typeof err === "object") {
		const headers = (err as OctokitErrorShape).response?.headers ?? {};
		const reset = headers["x-ratelimit-reset"] ?? headers["X-RateLimit-Reset"];
		const limit = headers["x-ratelimit-limit"] ?? headers["X-RateLimit-Limit"];
		if (reset) state.resources[r].resetAtMs = Number(reset) * 1000;
		if (limit) state.resources[r].limit = Number(limit);
	}

	return waitMs;
}

/** Switch to another ready token, or wait for the soonest reset. */
async function recoverFromRateLimit(
	err: unknown,
	attempt: number,
	attempts: number,
): Promise<void> {
	const limitedToken = pool.current;
	const resource = resourceFromError(err);
	const waitMs = markTokenRateLimited(limitedToken, resource, err, attempt);
	const readyIndex = chooseReadyToken(resource, 1);
	if (readyIndex !== null && readyIndex !== limitedToken) {
		switchToken(readyIndex, `${resource} fallback`);
		// chooseReadyToken filters on quota/cooldown but NOT on the per-token
		// minimum gap. Pace the fallback token here so we don't violate its gap
		// by retrying immediately after a fast back-to-back switch (mostly
		// relevant for search, which has a 2.1s floor).
		await paceMinimumGapForToken(pool.states[readyIndex], resource, 1);
		return;
	}
	const soonest = soonestToken(resource, 1);
	const sleepMs = Math.min(waitMs, soonest.waitMs);
	if (soonest.index !== null) switchToken(soonest.index, `${resource} reset soonest`);
	console.log(
		`  [retry] rate-limited (status ${(err as OctokitErrorShape).status}); waiting ${
			Math.ceil(sleepMs / 1000)
		}s (attempt ${attempt + 1}/${attempts})`,
	);
	await sleep(sleepMs);
}

/**
 * Run an Octokit call with rate-limit-aware retry. Rotates token if more than
 * one is configured; otherwise waits for the window to reset.
 */
export async function withRetry<T>(
	fn: (client: Octokit) => Promise<T>,
	{ maxAttempts, retryServerErrors = true }: RetryOptions = {},
): Promise<T> {
	let lastErr: unknown;
	const attempts = maxAttempts ?? Math.max(6, pool.states.length * 3);
	for (let attempt = 0; attempt < attempts; attempt++) {
		try {
			return await fn(getOctokit());
		} catch (err) {
			lastErr = err;
			if (isAuthError(err)) {
				disableCurrentToken((err as OctokitErrorShape).message ?? "auth error");
				if (rotateToken("auth fallback")) continue;
				throw err;
			}
			if (isRateLimitError(err)) {
				await recoverFromRateLimit(err, attempt, attempts);
				continue;
			}
			if (isTransientServerError(err)) {
				if (!retryServerErrors) throw err;
				const waitMs = Math.min(30_000, 1000 * 2 ** attempt);
				console.log(
					`  [retry] ${(err as OctokitErrorShape).status} server error; waiting ${
						waitMs / 1000
					}s (attempt ${attempt + 1}/${attempts})`,
				);
				if (attempt > 0) rotateToken("server-error fallback");
				await sleep(waitMs);
				continue;
			}
			throw err;
		}
	}
	throw lastErr;
}
