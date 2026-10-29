type ConsoleMethod = "log" | "warn" | "error";

let installed = false;

function timestamp(): string {
	return new Date().toISOString();
}

function prefixLines(value: string, prefix: string): string {
	return value
		.split("\n")
		.map((line) => `${prefix} ${line}`)
		.join("\n");
}

function wrap(method: ConsoleMethod): (...args: unknown[]) => void {
	const original = console[method].bind(console);
	return (...args: unknown[]) => {
		const prefix = `[${timestamp()}]`;
		if (args.length === 0) {
			original(prefix);
			return;
		}

		const [first, ...rest] = args;
		if (typeof first === "string") {
			original(prefixLines(first, prefix), ...rest);
			return;
		}
		original(prefix, first, ...rest);
	};
}

export function installTimestampedConsole(): void {
	if (installed) return;
	installed = true;

	console.log = wrap("log");
	console.warn = wrap("warn");
	console.error = wrap("error");
}
