/** Recover capped PR commit connections from saved base/head Git objects. */
import { join, resolve } from "@std/path";
import { MiningStore, type StoredRecord } from "./store.ts";

async function git(directory: string, args: string[]): Promise<string> {
	const child = new Deno.Command("git", {
		args: ["-C", directory, "-c", "credential.helper=", ...args],
		env: { GIT_TERMINAL_PROMPT: "0" },
		stdout: "piped",
		stderr: "piped",
	}).spawn();
	const timer = setTimeout(() => {
		try {
			child.kill("SIGKILL");
		} catch { /* exited */ }
	}, 120000);
	try {
		const result = await child.output();
		if (!result.success) {
			throw new Error(
				`Git ${args[0]} failed: ${new TextDecoder().decode(result.stderr).slice(0, 300)}`,
			);
		}
		return new TextDecoder().decode(result.stdout).trim();
	} finally {
		clearTimeout(timer);
	}
}
export function validateRange(shas: string[], known: string[], expected: number): void {
	const found = new Set(shas);
	if (
		found.size !== shas.length || found.size !== expected || known.some((sha) => !found.has(sha))
	) {
		throw new Error(
			`Git PR range validation failed: ${found.size}/${expected}; saved API SHAs must all match`,
		);
	}
}
export async function recoverCommits(
	store: MiningStore,
	run: string,
	repo: Record<string, unknown>,
	number: number,
	expected: number,
): Promise<void> {
	const id = String(repo.id);
	const saved = store.db.prepare(
		"SELECT data FROM records WHERE repo_id=? AND kind='pull' AND json_extract(data,'$.number')=?",
	).get(id, number);
	if (!saved) throw new Error(`Missing saved PR ${number}`);
	const pull = JSON.parse(String(saved.data));
	const base = pull.base?.sha, head = pull.head?.sha;
	if (![base, head].every((sha) => typeof sha === "string" && /^[a-f0-9]{40,64}$/.test(sha))) {
		throw new Error("Missing valid saved PR base/head");
	}
	const identity = store.db.prepare("SELECT requested_name FROM repositories WHERE id=?").get(id)!;
	const name = String(identity.requested_name);
	if (!/^[\w.-]+\/[\w.-]+$/.test(name)) throw new Error("Invalid repository name");
	const mirror = resolve(run, "mirrors", name.replace("/", "__") + ".git");
	let directory = mirror;
	const missing: string[] = [];
	for (const sha of [base, head]) {
		try {
			await git(mirror, ["cat-file", "-e", `${sha}^{commit}`]);
		} catch {
			missing.push(sha);
		}
	}
	if (missing.length) {
		directory = resolve(run, "recovery_mirrors", name.replace("/", "__") + ".git");
		await Deno.mkdir(directory, { recursive: true });
		await git(directory, ["init", "--bare"]);
		await Deno.mkdir(join(directory, "objects", "info"), { recursive: true });
		await Deno.writeTextFile(
			join(directory, "objects", "info", "alternates"),
			join(mirror, "objects") + "\n",
		);
		for (const sha of missing) {
			try {
				await git(directory, ["cat-file", "-e", `${sha}^{commit}`]);
				continue;
			} catch { /* fetch below */ }
			const source = sha === head ? pull.head?.repo?.full_name : pull.base?.repo?.full_name;
			if (typeof source !== "string" || !/^[\w.-]+\/[\w.-]+$/.test(source)) {
				throw new Error("Missing Git recovery source");
			}
			await git(directory, ["fetch", "--no-tags", `https://github.com/${source}.git`, sha]);
		}
	}
	const output = await git(directory, ["rev-list", `${base}..${head}`]);
	const shas = output ? output.split("\n") : [];
	const known = store.db.prepare(
		"SELECT data FROM records WHERE repo_id=? AND kind='pr_commit' AND json_extract(data,'$.pr_number')=?",
	).all(id, number);
	validateRange(shas, known.map((row) => JSON.parse(String(row.data)).commit.oid), expected);
	const existing = new Set(known.map((row) => JSON.parse(String(row.data)).commit.oid));
	const rows: StoredRecord[] = shas.filter((sha) => !existing.has(sha)).map((sha) => ({
		kind: "pr_commit",
		key: `${number}:${sha}`,
		data: { pr_number: number, commit: { oid: sha }, source: "git_base_head_recovery" },
	}));
	rows.push({
		kind: "pr_commit_recovery_audit",
		key: String(number),
		data: {
			pr_number: number,
			method: "git_rev_list_base_to_head",
			base,
			head,
			expected_count: expected,
			recovered_count: shas.length,
			saved_api_count: known.filter((row) =>
				JSON.parse(String(row.data)).source !== "git_base_head_recovery"
			).length,
			all_saved_api_shas_matched: true,
			object_store: directory,
			recovered_at: new Date().toISOString(),
		},
	});
	store.page(id, `pr:${number}:commits`, rows, { cursor: null, done: true });
}

export async function runRecovery(): Promise<void> {
	const argument = Deno.args.find((arg) => arg.startsWith("--run-dir="));
	if (!argument) throw new Error("--run-dir=PATH is required");
	const run = resolve(argument.slice(10));
	const store = new MiningStore(join(run, "github.sqlite"));
	let failed = 0;
	try {
		const failures = store.db.prepare(
			"SELECT repo,stage,error FROM failures WHERE stage LIKE 'pr:%'",
		).all();
		for (const failure of failures) {
			const match = String(failure.error).match(/Incomplete (\d+):commits: \d+\/(\d+)/);
			if (!match) continue;
			const repo = store.lookup(String(failure.repo));
			if (!repo) continue;
			try {
				await recoverCommits(store, run, repo, Number(match[1]), Number(match[2]));
				if (
					["commits", "reviews", "closingIssuesReferences"].every((key) =>
						store.getProgress(String(repo.id), `pr:${match[1]}:${key}`).done
					)
				) store.clearFailure(String(failure.repo), String(failure.stage));
				console.log(`${failure.repo} PR ${match[1]} recovered ${match[2]} commits`);
			} catch (error) {
				failed++;
				console.error(
					`${failure.repo} ${failure.stage}: ${
						error instanceof Error ? error.message : "recovery failed"
					}`,
				);
			}
		}
	} finally {
		store.close();
	}
	Deno.exitCode = failed ? 1 : 0;
}
