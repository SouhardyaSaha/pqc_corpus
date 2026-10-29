/**
 * Production GitHub access for the collector. Importing this module loads the
 * configured tokens, so offline tests import `session.ts` instead.
 */
import {
	describeRateState,
	paceCore,
	paceGraphql,
	setMinimumRequestGap,
	tokenCount,
	withRetry,
} from "../lib/github.ts";
import type { GitHubTransport, GraphqlRetry, RestResponse } from "./session.ts";

const REQUEST_TIMEOUT_MS = 45000;

export function createGitHubTransport(): GitHubTransport {
	setMinimumRequestGap("core", 1000);
	setMinimumRequestGap("graphql", 1000);
	return {
		tokenCount,
		describeRateState,
		async rest(path, params) {
			await paceCore();
			return await withRetry((client) =>
				client.request(`GET ${path}`, {
					...params,
					request: { timeout: REQUEST_TIMEOUT_MS },
					headers: { "X-GitHub-Api-Version": "2022-11-28" },
				})
			) as RestResponse;
		},
		async graphql<T>(query: string, variables: Record<string, unknown>, retry?: GraphqlRetry) {
			await paceGraphql();
			return await withRetry(
				(client) =>
					client.graphql<T>(query, {
						...variables,
						request: { timeout: REQUEST_TIMEOUT_MS },
					}),
				retry,
			);
		},
	};
}
