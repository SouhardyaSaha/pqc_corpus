/**
 * Project root resolution for the TypeScript workers.
 *
 *   pqc_corpus/
 *     collector/lib/   ← this file
 *     data/
 *     .env
 *
 * `PROJECT_ROOT` resolves to the directory that contains `collector/`, so commands
 * behave the same no matter where they are invoked from.
 */

import { fromFileUrl, resolve } from "@std/path";

/** Directory of this file: `collector/lib`. */
const THIS_DIR = fromFileUrl(new URL(".", import.meta.url));

export const PROJECT_ROOT = resolve(THIS_DIR, "..", "..");
