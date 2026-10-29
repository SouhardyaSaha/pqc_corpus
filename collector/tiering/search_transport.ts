/** GitHub search access needed for tier classification; tests provide fakes. */

export type SearchPage = {
	issueCount: number;
	nodes: Array<{ number: number }>;
	pageInfo: { hasNextPage: boolean; endCursor: string | null };
};

export type RepositoryMetadata = {
	databaseId: number;
	nameWithOwner: string;
	createdAt: string;
	pullRequests: { totalCount: number };
	issues: { totalCount: number };
};

export interface SearchTransport {
	/** Wait for search and GraphQL quota on one token. */
	paceSearch(): Promise<void>;
	searchPage(query: string, cursor: string | null): Promise<SearchPage>;
	/** Paced separately; returns null for an unavailable repository. */
	repositoryMetadata(owner: string, name: string): Promise<RepositoryMetadata | null>;
}
