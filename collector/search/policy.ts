import type { PlanCorpus } from "../api/config.ts";

/** Corpus A at or above the cutoff, B below it, "unrated" (corpus C) without PRs or issues. */
export function assignCorpus(matched: number, total: number, cutoff = 0.148): PlanCorpus {
	if (
		!Number.isSafeInteger(total) || !Number.isSafeInteger(matched) || total < 0 || matched < 0 ||
		matched > total
	) {
		throw new Error("Invalid corpus search counts; refusing an unverified classification");
	}
	if (!Number.isFinite(cutoff) || cutoff < 0 || cutoff > 1) throw new Error("Invalid cutoff");
	return total === 0 ? "unrated" : matched / total >= cutoff ? "A" : "B";
}
