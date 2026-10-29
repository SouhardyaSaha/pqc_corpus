import { nextPage, resumePage } from "../api/pagination.ts";
import { recoverCommits, validateRange } from "../api/recovery.ts";
import { MiningStore } from "../api/store.ts";
function equal(actual: unknown, expected: unknown) {
	if (JSON.stringify(actual) !== JSON.stringify(expected)) {
		throw new Error(`${actual} != ${expected}`);
	}
}
function rejects(action: () => unknown) {
	try {
		action();
	} catch {
		return;
	}
	throw new Error("Expected rejection");
}
Deno.test("legacy cursor replays last page and preserves opaque continuation links", () => {
	const path = "/repos/owner/repo/issues";
	equal(new URL(resumePage("100", path, "12", { state: "all" })).searchParams.get("page"), "99");
	const next = "https://api.github.com/repositories/12/issues?page=100&after=opaque%3D";
	equal(
		nextPage(
			`<${next}>; rel="next", <https://api.github.com/repositories/12/issues?before=x>; rel="prev"`,
			path,
			"12",
		),
		next,
	);
	equal(resumePage(next, path, "12", {}), next);
	equal(nextPage(undefined, path, "12"), null);
	for (
		const unsafe of [
			"https://evil.test/repos/owner/repo/issues",
			"https://api.github.com/repositories/13/issues",
			"https://secret@api.github.com/repos/owner/repo/issues",
		]
	) {
		rejects(() => nextPage(`<${unsafe}>; rel="next"`, path, "12"));
	}
});
Deno.test("Git recovery validates totals and the saved API subset atomically", async () => {
	const root = await Deno.makeTempDir();
	const mirror = `${root}/mirrors/owner__repo.git`;
	await Deno.mkdir(mirror, { recursive: true });
	async function git(...args: string[]) {
		const result = await new Deno.Command("git", {
			args: ["-C", mirror, ...args],
			stdout: "piped",
			stderr: "piped",
		}).output();
		if (!result.success) throw new Error(new TextDecoder().decode(result.stderr));
		return new TextDecoder().decode(result.stdout).trim();
	}
	const store = new MiningStore(`${root}/test.sqlite`);
	try {
		await git("init");
		await git(
			"-c",
			"user.name=Test",
			"-c",
			"user.email=test@example.test",
			"commit",
			"--allow-empty",
			"-m",
			"base",
		);
		const base = await git("rev-parse", "HEAD");
		await git(
			"-c",
			"user.name=Test",
			"-c",
			"user.email=test@example.test",
			"commit",
			"--allow-empty",
			"-m",
			"change one",
		);
		const first = await git("rev-parse", "HEAD");
		await git(
			"-c",
			"user.name=Test",
			"-c",
			"user.email=test@example.test",
			"commit",
			"--allow-empty",
			"-m",
			"change two",
		);
		const head = await git("rev-parse", "HEAD");
		const repo = { id: "12", full_name: "owner/repo" };
		store.repository("owner/repo", repo);
		store.page("12", "pulls", [{
			kind: "pull",
			key: "1",
			data: { number: 1, base: { sha: base }, head: { sha: head } },
		}], { cursor: null, done: true });
		store.page("12", "pr:1:commits", [{
			kind: "pr_commit",
			key: `1:${first}`,
			data: { pr_number: 1, commit: { oid: first } },
		}], { cursor: null, done: false });
		let failed = false;
		try {
			await recoverCommits(store, root, repo, 1, 3);
		} catch {
			failed = true;
		}
		equal(failed, true);
		equal(store.getProgress("12", "pr:1:commits").done, false);
		equal(store.db.prepare("SELECT count(*) AS n FROM records WHERE kind='pr_commit'").get()!.n, 1);
		rejects(() => validateRange([first, head], [base], 2));
		rejects(() => validateRange([first, first], [first], 2));
		await recoverCommits(store, root, repo, 1, 2);
		await recoverCommits(store, root, repo, 1, 2);
		equal(store.getProgress("12", "pr:1:commits").done, true);
		equal(store.db.prepare("SELECT count(*) AS n FROM records WHERE kind='pr_commit'").get()!.n, 2);
		equal(
			store.db.prepare("SELECT count(*) AS n FROM records WHERE kind='pr_commit_recovery_audit'")
				.get()!.n,
			1,
		);
	} finally {
		store.close();
		await Deno.remove(root, { recursive: true });
	}
});
