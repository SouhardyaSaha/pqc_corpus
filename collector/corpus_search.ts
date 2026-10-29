/** Stable command entry point. */
if (import.meta.main) {
	if (Deno.args.includes("--help") || Deno.args.includes("-h")) {
		console.log("Usage: corpus_search.ts --run-dir=PATH --repo=OWNER/REPO");
	} else {
		const { runCorpusSearch } = await import("./search/search.ts");
		await runCorpusSearch();
	}
}
