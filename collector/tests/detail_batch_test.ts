import {
	buildDetailBatch,
	type DetailRequest,
	detailStreams,
	fetchDetailBatch,
} from "../api/detail_batch.ts";
import { MiningStore } from "../api/store.ts";
function assert(value: unknown, message = "Assertion failed"): asserts value {
	if (!value) throw new Error(message);
}
function request(number: number): DetailRequest {
	return {
		number,
		progress: {
			commits: { cursor: null, done: false },
			reviews: { cursor: null, done: false },
			closingIssuesReferences: { cursor: null, done: false },
		},
	};
}
const options = { check() {}, canSplit: () => true, onSplit() {} };
Deno.test("batch resumes each saved connection independently and excludes completed streams", () => {
	const store = new MiningStore(":memory:");
	try {
		store.page("1", "pr:7:commits", [], { cursor: "opaque-seven", done: false });
		store.page("1", "pr:7:reviews", [], { cursor: null, done: true });
		store.page("1", "pr:8:commits", [], { cursor: "opaque-eight", done: false });
		const requests = [7, 8].map((number) => ({
			number,
			progress: Object.fromEntries(detailStreams.map((stream) => [
				stream,
				store.getProgress("1", `pr:${number}:${stream}`),
			])) as DetailRequest["progress"],
		}));
		const { query, variables } = buildDetailBatch(requests);
		assert(variables.c_7_commits === "opaque-seven");
		assert(variables.c_8_commits === "opaque-eight");
		assert(!("c_7_reviews" in variables));
		assert(!query.includes("$c_7_reviews"));
		assert(query.includes("pr_7:pullRequest(number:7)"));
		assert(query.includes("pr_8:pullRequest(number:8)"));
		assert(query.includes("first:100"));
	} finally {
		store.close();
	}
});
Deno.test("batch maps response aliases to PR numbers regardless of response order", async () => {
	const first = {
		commits: {
			nodes: [{ commit: { oid: "one" } }],
			totalCount: 1,
			pageInfo: { hasNextPage: false, endCursor: null },
		},
	};
	const second = {
		reviews: { nodes: [], totalCount: 0, pageInfo: { hasNextPage: false, endCursor: null } },
	};
	const result = await fetchDetailBatch(
		[request(7), request(8), request(9)],
		() => Promise.resolve({ repository: { pr_8: second, pr_7: first, pr_9: null } }),
		options,
	);
	const seven = result.get(7)!;
	const eight = result.get(8)!;
	const nine = result.get(9)!;
	assert("page" in seven && seven.page === first);
	assert("page" in eight && eight.page === second);
	assert("page" in nine && nine.page === null);
});
Deno.test("one failing PR is isolated without dropping successful neighbors or advancing storage", async () => {
	let calls = 0;
	const result = await fetchDetailBatch([request(1), request(2), request(3)], ({ query }) => {
		calls++;
		if (query.includes("pr_2:")) throw new Error("PR unavailable");
		const repository: Record<string, {}> = {};
		for (const number of [1, 3]) {
			if (query.includes(`pr_${number}:`)) repository[`pr_${number}`] = {};
		}
		return Promise.resolve({ repository });
	}, options);
	assert(calls === 5);
	assert("page" in result.get(1)!);
	assert("error" in result.get(2)!);
	assert("page" in result.get(3)!);
});
Deno.test("exhausted quota errors do not fan out into more batch requests", async () => {
	let calls = 0;
	const error = new Error("rate limit");
	const result = await fetchDetailBatch([request(1), request(2)], () => {
		calls++;
		throw error;
	}, { ...options, canSplit: () => false });
	assert(calls === 1);
	assert([...result.values()].every((v) => "error" in v && v.error === error));
});
Deno.test("pause aborts recursive fallback instead of recording PR failures", async () => {
	let calls = 0;
	const pause = new Error("paused");
	let caught: unknown;
	try {
		await fetchDetailBatch([request(1), request(2)], () => {
			calls++;
			throw new Error("timeout");
		}, {
			...options,
			check() {
				if (calls) throw pause;
			},
		});
	} catch (error) {
		caught = error;
	}
	assert(caught === pause);
	assert(calls === 1);
});
Deno.test("invalid, duplicate, oversized and entirely completed batches are rejected", () => {
	const complete = request(1);
	for (const stream of detailStreams) complete.progress[stream].done = true;
	for (
		const input of [
			[],
			[request(-1)],
			[request(1), request(1)],
			Array.from({ length: 21 }, (_, i) => request(i + 1)),
			[complete],
		]
	) {
		let threw = false;
		try {
			buildDetailBatch(input);
		} catch {
			threw = true;
		}
		assert(threw);
	}
});
