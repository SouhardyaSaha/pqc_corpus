/** Cooperative shutdown: workers poll this flag and checkpoint before exiting. */

export interface StopRequest {
	readonly requested: boolean;
}

/** Record SIGINT/SIGTERM instead of terminating immediately. */
export function listenForStop(): StopRequest {
	const state = { requested: false };
	for (const signal of ["SIGINT", "SIGTERM"] as const) {
		Deno.addSignalListener(signal, () => {
			state.requested = true;
		});
	}
	return state;
}
