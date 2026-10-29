/** CLI help must work without tokens, network permissions, or collection inputs. */
Deno.test("existing worker commands show help without initializing collectors", async () => {
	for (const name of ["collect_api.ts", "corpus_search.ts", "recover_commits.ts"]) {
		const file = new URL(`../${name}`, import.meta.url);
		const result = await new Deno.Command(Deno.execPath(), {
			args: ["run", "--no-config", "--deny-net", file.pathname, "--help"],
			stdout: "piped",
			stderr: "piped",
		}).output();
		const stdout = new TextDecoder().decode(result.stdout);
		const stderr = new TextDecoder().decode(result.stderr);
		if (!result.success || !stdout.includes(`Usage: ${name}`)) {
			throw new Error(`${name}: ${stdout} ${stderr}`);
		}
	}
});
