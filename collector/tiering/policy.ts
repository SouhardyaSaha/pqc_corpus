export function assignTier(matched: number, total: number, cutoff = 0.148): "A" | "B" | "unrated" {
	if (
		!Number.isSafeInteger(total) || !Number.isSafeInteger(matched) || total < 0 || matched < 0 ||
		matched > total
	) {
		throw new Error("Invalid tier counts; refusing an unverified classification");
	}
	if (!Number.isFinite(cutoff) || cutoff < 0 || cutoff > 1) throw new Error("Invalid cutoff");
	return total === 0 ? "unrated" : matched / total >= cutoff ? "A" : "B";
}
