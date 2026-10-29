/** Stable command entry point. */
if (import.meta.main) {
	if (Deno.args.includes("--help") || Deno.args.includes("-h")) {
		console.log(
			"Usage: collect_api.ts --run-dir=PATH [--only-repo=OWNER/REPO] [--pr-batch-size=10]",
		);
	} else {
		const { runCollector } = await import("./api/collector.ts");
		await runCollector();
	}
}
