/**
 * Per-token rate-limit bookkeeping.
 *
 * State is populated from the `X-RateLimit-*` headers attached to every response,
 * so no request is spent just to check a rate limit.
 */

export type Resource = "core" | "search" | "graphql";

export interface ResourceState {
	/** Calls remaining in this token's current window. */
	remaining: number;
	/** Window reset time, epoch ms. */
	resetAtMs: number;
	/** Total quota in this window (for logging). */
	limit: number;
}

/** Quota and pacing state tracked independently for each configured token. */
export interface QuotaState {
	resources: Record<Resource, ResourceState>;
	lastRequestAtMs: Record<Resource, number>;
	cooldownUntilMs: Record<Resource, number>;
	disabled: boolean;
}

function initialState(): ResourceState {
	return { remaining: Number.POSITIVE_INFINITY, resetAtMs: 0, limit: 0 };
}

export function initialResourceStates(): Record<Resource, ResourceState> {
	return { core: initialState(), search: initialState(), graphql: initialState() };
}

export function zeroTimes(): Record<Resource, number> {
	return { core: 0, search: 0, graphql: 0 };
}

export function classifyResource(url: string, resourceHeader?: string): Resource {
	if (resourceHeader === "search" || resourceHeader === "graphql" || resourceHeader === "core") {
		return resourceHeader;
	}
	if (url.includes("/graphql")) return "graphql";
	if (url.includes("/search/")) return "search";
	return "core";
}

function readHeader(headers: unknown, key: string): string | undefined {
	if (!headers || typeof headers !== "object") return undefined;
	const h = headers as Record<string, unknown>;
	const v = h[key] ?? h[key.toLowerCase()];
	if (typeof v === "string") return v;
	if (typeof v === "number") return String(v);
	return undefined;
}

/** Record the quota reported by a successful response for the token that sent it. */
export function updateFromHeaders(state: QuotaState, url: string, headers: unknown): void {
	const remaining = readHeader(headers, "x-ratelimit-remaining");
	const reset = readHeader(headers, "x-ratelimit-reset");
	const limit = readHeader(headers, "x-ratelimit-limit");
	const resource = readHeader(headers, "x-ratelimit-resource");
	if (remaining === undefined || reset === undefined) return;

	const r = classifyResource(url, resource);
	state.resources[r].remaining = Number(remaining);
	state.resources[r].resetAtMs = Number(reset) * 1000;
	if (limit !== undefined) state.resources[r].limit = Number(limit);
	if (state.resources[r].remaining > 0) state.cooldownUntilMs[r] = 0;
}

export function formatResourceState(label: string, s: ResourceState): string {
	const rem = Number.isFinite(s.remaining) ? s.remaining : "?";
	const lim = s.limit || "?";
	const reset = s.resetAtMs > 0
		? `reset in ${Math.max(0, Math.ceil((s.resetAtMs - Date.now()) / 1000))}s`
		: "reset ?";
	return `${label}=${rem}/${lim} (${reset})`;
}
