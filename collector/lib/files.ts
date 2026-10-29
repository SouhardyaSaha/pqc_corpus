/** Small JSON file helpers shared by the workers. */

/** Replace a JSON file by writing a temporary sibling and renaming it. */
export async function writeJsonAtomic(path: string, data: unknown): Promise<void> {
	await Deno.writeTextFile(path + ".tmp", JSON.stringify(data, null, 2) + "\n");
	await Deno.rename(path + ".tmp", path);
}

/** Parse a JSON file, or return null when it does not exist yet. */
export async function readJsonIfExists<T = unknown>(path: string): Promise<T | null> {
	try {
		return JSON.parse(await Deno.readTextFile(path)) as T;
	} catch (e) {
		if (e instanceof Deno.errors.NotFound) return null;
		throw e;
	}
}
