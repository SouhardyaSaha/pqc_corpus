/**
 * Production GitHub search access for tier classification. Importing this
 * module loads the configured tokens.
 */
import { paceGraphql, paceGraphqlSearch, withRetry } from "../lib/github.ts";
import type { RepositoryMetadata, SearchPage, SearchTransport } from "./search_transport.ts";

const SEARCH_QUERY =
	`query($q:String!,$cursor:String){search(query:$q,type:ISSUE,first:100,after:$cursor){issueCount nodes{... on PullRequest{number} ... on Issue{number}} pageInfo{hasNextPage endCursor}}}`;

const METADATA_QUERY =
	`query($owner:String!,$name:String!){repository(owner:$owner,name:$name){databaseId nameWithOwner createdAt pullRequests{totalCount} issues{totalCount}}}`;

export const githubSearchTransport: SearchTransport = {
	paceSearch: () => paceGraphqlSearch(),
	async searchPage(query, cursor) {
		const result = await withRetry((client) =>
			client.graphql<{ search: SearchPage }>(SEARCH_QUERY, {
				q: query,
				cursor,
				request: { timeout: 45000 },
			})
		);
		return result.search;
	},
	async repositoryMetadata(owner, name) {
		await paceGraphql();
		const response = await withRetry((client) =>
			client.graphql<{ repository: RepositoryMetadata | null }>(METADATA_QUERY, { owner, name })
		);
		return response.repository;
	},
};
