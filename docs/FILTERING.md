# Filtered sets

`filter` reads a mined file and keeps a subset of its lines, unchanged and in the
same order. Every rule is a fixed, scripted check; nothing is decided by hand or by
a model. Each removed record is listed with its reason in the report directory.

## Commits: 114,361 → 47,729

Each step runs on what the previous steps left, so the counts do not overlap.

| Step | Removes | Removed | Left |
|---|---|---:|---:|
| | mined | | 114,361 |
| 1. `eligibility` | commits on no default branch and in no merged pull request (side branches, unmerged proposals) | 41,285 | 73,076 |
| 2. `rebased_copies` | a pull request's original commit when a rebase-merge copy of it is on the default branch | 2,175 | 70,901 |
| 3. `merge_repeats` | a merge commit whose patch repeats a non-merge commit of the same repository | 2,443 | 68,458 |
| 4. `squash_copies` | a pull request's original commit when a squash-merge copy of it (subject ending in `(#N)`) is on the default branch | 1,587 | 66,871 |
| 5. `merge_commits` | a merge commit whose merged branch tip is still in the set | 3,067 | 63,804 |
| 6. `fork_history` | in a fork, inherited commits with no PQC term (only open-quantum-safe/openssh is a fork) | 11,375 | 52,429 |
| 7. `general_libraries` | commits with no PQC term in a repository whose name, description and topics are not about PQC | 1,934 | 50,495 |
| 8. `housekeeping` | commits that change no files, or whose diff names no PQC term and that change only CI configuration, only lock files, only repository metadata files, or were made by a bot | 2,766 | 47,729 |

**Duplicates (steps 2–5).** Two commits carry the same change when their *patch id*
is equal: the patch with `index` lines removed and hunk line numbers blanked, hashed
(German, Adams & Hassan, *Empirical Software Engineering* 21(1), 2016). Step 2 is
stricter: same message, author e-mail (compared by `author_key`), author time and
per-file line counts, and a byte-identical patch apart from `index` lines. A duplicate step removes a copy only
when it can tell which one to keep (exactly one copy on the default branch, or the
non-merge commit); otherwise it keeps the whole group. The change stays in the set
through the copy kept.

**"No PQC term" (steps 6–8)** means no term in the commit message, in the titles and
bodies of the pull requests GitHub associates with it or of the issues they close
(`pqc_in_linked_text`), in the changed file paths, or in the added and removed lines
(step 8: anywhere in the diff). For the released data, `pqc_in_linked_text` was
observed on 29 September 2026 and also counts keyword matches that collection-time
enrichment recorded for the commit. The terms (`pqc_corpus/filters/terms.py`) are
99 scheme names with their spellings and parameter sets, and generic terms such as
post-quantum, liboqs and FIPS 203. Names that are ordinary words (CROSS, LESS, Falcon)
match only in their exact spelling or with a parameter set. A patch over 64 MiB is not
scanned and counts as naming a term, so no keyword step removes it.

**Limits.**
- Step 5 checks only that the merged branch's tip is present, not every merged commit.
  In a few corpus B repositories, where only matching commits were collected, a removed
  merge commit was the set's only record of some merged work.
- Steps 6–8 depend on the term list; a PQC change that names no term in any of the
  places above, in a repository not named for PQC, is removed.
- `pqc_in_linked_text` is an observation: a new run computes it from GitHub at mining
  time, without the enrichment's keyword matches, so it can differ slightly for the
  same commit.

## Issues: 5,713 → 5,687

| Step | Removes | Removed | Left |
|---|---|---:|---:|
| | mined | | 5,713 |
| 1. `bot_issues` | issues opened by a bot account (a login ending in `[bot]`) | 26 | 5,687 |

The 26 are mirrors of issues in a sister repository (whose originals stay), tasks
copied from pull requests, automated CI and test-vector reports, and a policy notice.
Bot comments inside issues written by people are kept.
