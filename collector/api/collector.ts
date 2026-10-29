/**
 * Collector entry point: resumable collection of a full raw run, or of one
 * repository's frozen tier selection.
 *
 * Exit codes: 0 complete, 2 complete with recorded gaps, 130 paused, 1 failed.
 */
import { join } from "@std/path";
import { safeErrorMessage } from "../lib/errors.ts";
import { installTimestampedConsole } from "../lib/logging.ts";
import { listenForStop } from "../lib/signals.ts";
import { loadManifest, loadTierPlan, parseCollectorArgs } from "./config.ts";
import { createGitHubTransport } from "./github_transport.ts";
import { collectPhases } from "./phases.ts";
import { CollectorSession, Paused } from "./session.ts";
import { MiningStore } from "./store.ts";

export async function runCollector(): Promise<void> {
	installTimestampedConsole();
	const stop = listenForStop();
	const options = parseCollectorArgs(Deno.args);
	const manifest = await loadManifest(options.run, options.onlyRepo);
	const tierPlan = await loadTierPlan(options.run, manifest, options.onlyRepo);

	const store = new MiningStore(join(options.run, "github.sqlite"));
	const transport = createGitHubTransport();
	const session = new CollectorSession(options.run, store, transport, stop, {
		pid: Deno.pid,
		worker: "api",
		started_at: new Date().toISOString(),
		tokens: transport.tokenCount(),
		pr_batch_size: options.batchSize,
		selection: tierPlan ? `tier_${tierPlan.tier}` : "raw_all",
	});
	try {
		Deno.exitCode = await collectPhases(session, manifest, tierPlan, options.batchSize);
	} catch (error) {
		await session.report({
			status: error instanceof Paused ? error.message : "failed",
			error: safeErrorMessage(error),
		});
		console.error(safeErrorMessage(error));
		Deno.exitCode = error instanceof Paused ? 130 : 1;
	} finally {
		store.close();
	}

	// Octokit may retain idle timers; all page writes and status updates are complete.
	Deno.exit(Deno.exitCode ?? 0);
}
