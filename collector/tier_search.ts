/** Stable command entry point. */
if (import.meta.main) {
	if (Deno.args.includes("--help") || Deno.args.includes("-h")) {
		console.log("Usage: tier_search.ts --run-dir=PATH --repo=OWNER/REPO");
	} else {
		const { runTierSearch } = await import("./tiering/search.ts");
		await runTierSearch();
	}
}
