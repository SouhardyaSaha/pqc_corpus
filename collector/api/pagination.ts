/** Follow GitHub's opaque cursor links; legacy page checkpoints replay one page. */
export function checkedPage(url: string, path: string, repoId: string): string {
	const parsed = new URL(url);
	const suffix = path.replace(/^\/repos\/[^/]+\/[^/]+/, "");
	if (
		parsed.origin !== "https://api.github.com" || parsed.username || parsed.password ||
		![path, `/repositories/${repoId}${suffix}`].includes(parsed.pathname)
	) {
		throw new Error("Unexpected pagination URL");
	}
	return parsed.href;
}
export function resumePage(
	cursor: string | null,
	path: string,
	repoId: string,
	params: Record<string, unknown>,
): string {
	if (cursor && !/^\d+$/.test(cursor)) return checkedPage(cursor, path, repoId);
	const url = new URL(path, "https://api.github.com");
	for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value));
	url.searchParams.set("per_page", "100");
	url.searchParams.set("page", String(Math.max(1, Number(cursor ?? 1) - 1)));
	return url.href;
}
export function nextPage(link: string | undefined, path: string, repoId: string): string | null {
	for (const part of (link ?? "").split(/,\s*(?=<)/)) {
		const match = part.match(/<([^>]+)>;\s*rel="([^"]+)"/);
		if (match?.[2].split(" ").includes("next")) return checkedPage(match[1], path, repoId);
	}
	if (link?.includes('rel="next"')) throw new Error("Malformed pagination link");
	return null;
}
