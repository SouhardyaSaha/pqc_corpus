/** API records and pagination checkpoints are committed in the same transaction. */
import { DatabaseSync } from "node:sqlite";

export type StoredRecord = { kind: string; key: string; data: Record<string, unknown> };
export type Progress = { cursor: string | null; done: boolean };

export class MiningStore {
	readonly db: DatabaseSync;
	constructor(path: string) {
		this.db = new DatabaseSync(path);
		this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
		CREATE TABLE IF NOT EXISTS repositories (
			id TEXT PRIMARY KEY, requested_name TEXT, full_name TEXT, data TEXT, fetched_at TEXT);
		CREATE TABLE IF NOT EXISTS records (
			repo_id TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL,
			data TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY(repo_id,kind,key));
		CREATE INDEX IF NOT EXISTS record_pr_number ON records(repo_id,kind,json_extract(data,'$.pr_number'));
		CREATE TABLE IF NOT EXISTS progress (
			repo_id TEXT NOT NULL, stream TEXT NOT NULL, cursor TEXT, done INTEGER NOT NULL,
			updated_at TEXT NOT NULL, PRIMARY KEY(repo_id,stream));
		CREATE TABLE IF NOT EXISTS failures (
			repo TEXT NOT NULL, stage TEXT NOT NULL, error TEXT NOT NULL, updated_at TEXT NOT NULL,
			PRIMARY KEY(repo,stage));
		CREATE TABLE IF NOT EXISTS aliases (requested_name TEXT PRIMARY KEY, repo_id TEXT NOT NULL);`);
	}
	getProgress(repo: string, stream: string): Progress {
		const row = this.db.prepare("SELECT cursor,done FROM progress WHERE repo_id=? AND stream=?")
			.get(repo, stream);
		return row
			? { cursor: row.cursor as string | null, done: Boolean(row.done) }
			: { cursor: null, done: false };
	}
	page(repo: string, stream: string, rows: StoredRecord[], progress: Progress): void {
		this.db.exec("BEGIN IMMEDIATE");
		try {
			const now = new Date().toISOString();
			const insert = this.db.prepare("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?)");
			for (const row of rows) insert.run(repo, row.kind, row.key, JSON.stringify(row.data), now);
			this.db.prepare("INSERT OR REPLACE INTO progress VALUES (?,?,?,?,?)")
				.run(repo, stream, progress.cursor, Number(progress.done), now);
			this.db.exec("COMMIT");
		} catch (error) {
			this.db.exec("ROLLBACK");
			throw error;
		}
	}
	repository(requested: string, row: Record<string, unknown>): void {
		this.db.exec("BEGIN IMMEDIATE");
		try {
			this.db.prepare("INSERT OR REPLACE INTO repositories VALUES (?,?,?,?,?)")
				.run(
					String(row.id),
					requested,
					String(row.full_name),
					JSON.stringify(row),
					new Date().toISOString(),
				);
			this.db.prepare("INSERT OR REPLACE INTO aliases VALUES (?,?)").run(
				requested.toLowerCase(),
				String(row.id),
			);
			this.db.exec("COMMIT");
		} catch (error) {
			this.db.exec("ROLLBACK");
			throw error;
		}
	}
	lookup(requested: string): Record<string, unknown> | undefined {
		const row = this.db.prepare(
			"SELECT r.data FROM repositories r JOIN aliases a ON a.repo_id=r.id WHERE a.requested_name=?",
		)
			.get(requested.toLowerCase());
		return row ? JSON.parse(String(row.data)) : undefined;
	}
	failure(repo: string, stage: string, error: string): void {
		this.db.prepare("INSERT OR REPLACE INTO failures VALUES (?,?,?,?)")
			.run(repo, stage, error, new Date().toISOString());
	}
	clearFailure(repo: string, stage: string): void {
		this.db.prepare("DELETE FROM failures WHERE repo=? AND stage=?").run(repo, stage);
	}
	/** Reopen a stream whose saved records do not match GitHub's reported total. */
	resetProgress(repo: string, stream: string): void {
		this.db.prepare("UPDATE progress SET done=0,cursor=NULL WHERE repo_id=? AND stream=?")
			.run(repo, stream);
	}
	/** Records of one kind saved for a pull request (commit links, reviews, ...). */
	countPullRecords(repo: string, kind: string, pullNumber: number): number {
		const row = this.db.prepare(
			"SELECT count(*) AS n FROM records WHERE repo_id=? AND kind=? AND json_extract(data,'$.pr_number')=?",
		).get(repo, kind, pullNumber)!;
		return Number(row.n);
	}
	hasItem(repo: string, kind: string, number: number): boolean {
		return Boolean(
			this.db.prepare(
				"SELECT 1 FROM records WHERE repo_id=? AND kind=? AND json_extract(data,'$.number')=?",
			).get(repo, kind, number),
		);
	}
	/** Saved PR or issue numbers in storage order. */
	itemNumbers(repo: string, kind: "pull" | "issue"): number[] {
		const sql = kind === "pull"
			? "SELECT json_extract(data,'$.number') AS number FROM records WHERE repo_id=? AND kind='pull'"
			: "SELECT json_extract(data,'$.number') AS number FROM records WHERE repo_id=? AND kind='issue'";
		return this.db.prepare(sql).all(repo).map((row) => Number(row.number));
	}
	/** Saved PR numbers in ascending order; numbers only, not large PR payloads. */
	pullNumbersAscending(repo: string): number[] {
		return this.db.prepare(
			"SELECT json_extract(data,'$.number') AS number FROM records WHERE repo_id=? AND kind='pull' ORDER BY number",
		).all(repo).map((row) => Number(row.number));
	}
	failures(): Array<Record<string, unknown>> {
		return this.db.prepare("SELECT repo,stage,error FROM failures").all();
	}
	recordCounts(): Array<Record<string, unknown>> {
		return this.db.prepare("SELECT kind,count(*) AS records FROM records GROUP BY kind").all();
	}
	close(): void {
		this.db.close();
	}
}
