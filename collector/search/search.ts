/** Corpus search entry point for one repository of a prepared run. */
import { errorMessage, redactTokens } from "../lib/errors.ts";
import { installTimestampedConsole } from "../lib/logging.ts";
import { listenForStop } from "../lib/signals.ts";
import { classifyRepository, loadTarget } from "./classify.ts";
import { githubSearchTransport } from "./github_search.ts";

export async function runCorpusSearch(): Promise<void> {
	installTimestampedConsole();
	const target = await loadTarget(Deno.args);
	await Deno.mkdir(target.cacheDir, { recursive: true });
	const stop = listenForStop();
	const check = () => {
		if (stop.requested) throw new Error("paused");
	};
	try {
		await classifyRepository(target, githubSearchTransport, check);
	} catch (error) {
		console.error(redactTokens(errorMessage(error)).slice(0, 600));
		Deno.exit(1);
	}
	Deno.exit(0);
}
