/** Error text that is safe to log or store in collection databases. */

const TOKEN_PATTERN = /(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)/g;

/** Replace anything shaped like a GitHub token. */
export function redactTokens(text: string): string {
	return text.replace(TOKEN_PATTERN, "[redacted]");
}

export function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

/**
 * Describe an API failure without serializing request objects, headers, or
 * authentication material. The HTTP status is kept when one is available.
 */
export function safeErrorMessage(error: unknown): string {
	const status = (error as { status?: number })?.status;
	return redactTokens(`${status ? `HTTP ${status}: ` : ""}${errorMessage(error)}`.slice(0, 500));
}
