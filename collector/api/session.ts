/**
 * Runtime context shared by the collection phases: the store, request pacing,
 * pause checks, and the live `api_status.json` file.
 */
import { statfsSync } from "node:fs";
import { join } from "@std/path";
import { writeJsonAtomic } from "../lib/files.ts";
import type { StopRequest } from "../lib/signals.ts";
import type { MiningStore } from "./store.ts";

/** GitHub repository object as returned by the REST API. */
export type Repository = Record<string, unknown>;

export type RestResponse = { data: unknown; headers: { link?: string } };

export type GraphqlRetry = { maxAttempts?: number; retryServerErrors?: boolean };

/**
 * GitHub access used by the collector. The production implementation paces
 * per token and retries; tests substitute canned responses.
 */
export interface GitHubTransport {
	tokenCount(): number;
	describeRateState(): string;
	rest(path: string, params: Record<string, unknown>): Promise<RestResponse>;
	graphql<T>(query: string, variables: Record<string, unknown>, retry?: GraphqlRetry): Promise<T>;
}

/** A clean stop (signal or low disk). Checkpoints are intact; the run can resume. */
export class Paused extends Error {}

const MINIMUM_FREE_BYTES = 20 * 1024 ** 3;
const REQUEST_GAP_MS = 1000;

export class CollectorSession {
	private calls = 0;
	private lastRequest = 0;
	private status: Record<string, unknown>;

	constructor(
		readonly run: string,
		readonly store: MiningStore,
		readonly transport: GitHubTransport,
		private readonly stop: StopRequest,
		initialStatus: Record<string, unknown>,
		private readonly requestGapMs = REQUEST_GAP_MS,
	) {
		this.status = initialStatus;
	}

	/** Throw {@link Paused} after a stop request or when free disk space is low. */
	check(): void {
		if (this.stop.requested) throw new Paused("paused");
		const disk = statfsSync(this.run);
		if (Number(disk.bavail) * Number(disk.bsize) < MINIMUM_FREE_BYTES) {
			throw new Paused("paused_low_disk");
		}
	}

	async report(values: Record<string, unknown>): Promise<void> {
		this.status = {
			...this.status,
			...values,
			updated_at: new Date().toISOString(),
			requests_this_process: this.calls,
		};
		await writeJsonAtomic(join(this.run, "api_status.json"), this.status);
	}

	async rest(path: string, params: Record<string, unknown> = {}): Promise<RestResponse> {
		await this.gap();
		return await this.transport.rest(path, params);
	}

	async graphql<T>(
		query: string,
		variables: Record<string, unknown>,
		retry?: GraphqlRetry,
	): Promise<T> {
		await this.gap();
		return await this.transport.graphql<T>(query, variables, retry);
	}

	describeRateState(): string {
		return this.transport.describeRateState();
	}

	/** Global pacing also applies across token switches. */
	private async gap(): Promise<void> {
		this.check();
		const wait = this.requestGapMs - (Date.now() - this.lastRequest);
		if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
		this.check();
		this.lastRequest = Date.now();
		this.calls++;
	}
}
