/** Stable command entry point. */
if (import.meta.main) {
	if (Deno.args.includes("--help") || Deno.args.includes("-h")) {
		console.log("Usage: recover_commits.ts --run-dir=PATH");
	} else {
		const { runRecovery } = await import("./api/recovery.ts");
		await runRecovery();
	}
}
