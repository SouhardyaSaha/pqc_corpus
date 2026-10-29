/**
 * Shared GitHub client.
 *
 * Goals:
 *   • Never spend a request just to check a rate limit. We piggyback on
 *     `X-RateLimit-*` headers attached to every successful response.
 *   • Sleep only when we're actually about to be throttled.
 *   • Honor `Retry-After` and `X-RateLimit-Reset` precisely on 403/429.
 *   • Track each configured token independently and proactively choose a
 *     token with available quota before waiting.
 *
 * Importing this module loads the configured tokens (see `github/tokens.ts`).
 * Implementation modules:
 *   github/rate_state.ts  quota state parsed from response headers
 *   github/tokens.ts      token pool, current token, status text
 *   github/quota.ts       quota checks and token choice
 *   github/pacing.ts      waits before requests
 *   github/retry.ts       retries, token fallback, and backoff
 */

export type { Resource } from "./github/rate_state.ts";
export { describeRateState, getOctokit, tokenCount } from "./github/tokens.ts";
export {
	paceCore,
	paceGraphql,
	paceGraphqlSearch,
	paceSearch,
	setMinimumRequestGap,
	sleep,
} from "./github/pacing.ts";
export { type RetryOptions, withRetry } from "./github/retry.ts";
