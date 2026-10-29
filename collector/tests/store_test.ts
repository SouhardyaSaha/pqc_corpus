import { MiningStore } from "../api/store.ts";
function assert(value: unknown, message = "Assertion failed"): asserts value {
	if (!value) throw new Error(message);
}
Deno.test("API pages resume without duplication and failed transactions do not advance cursors", () => {
	const path = Deno.makeTempFileSync();
	let store = new MiningStore(path);
	try {
		store.page("42", "issues", [{ kind: "issue", key: "8", data: { id: 8, number: 1 } }], {
			cursor: "2",
			done: false,
		});
		store.page("42", "issues", [{ kind: "issue", key: "8", data: { id: 8, number: 1 } }], {
			cursor: "2",
			done: false,
		});
		const circular: Record<string, unknown> = {};
		circular.self = circular;
		let failed = false;
		try {
			store.page("42", "issues", [
				{ kind: "issue", key: "9", data: { id: 9 } },
				{ kind: "issue", key: "10", data: circular },
			], { cursor: "3", done: true });
		} catch {
			failed = true;
		}
		assert(failed);
		store.close();
		store = new MiningStore(path);
		assert(store.getProgress("42", "issues").cursor === "2");
		assert(!store.getProgress("42", "issues").done);
		assert(store.db.prepare("SELECT count(*) AS n FROM records").get()!.n === 1);
	} finally {
		store.close();
		Deno.removeSync(path);
	}
});
Deno.test("repository aliases share stable GitHub identity without mixing streams", () => {
	const path = Deno.makeTempFileSync();
	const store = new MiningStore(path);
	try {
		store.repository("Old/Repo", { id: 42, full_name: "New/Repo" });
		store.repository("new/repo", { id: 42, full_name: "New/Repo" });
		assert(store.lookup("OLD/REPO")?.id === 42);
		assert(store.lookup("New/Repo")?.id === 42);
		store.page("42", "pulls", [], { cursor: "2", done: true });
		assert(!store.getProgress("42", "issues").done);
		assert(store.getProgress("42", "pulls").done);
	} finally {
		store.close();
		Deno.removeSync(path);
	}
});
