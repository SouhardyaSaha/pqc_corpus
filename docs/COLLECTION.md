# How a run is collected

`python -m pqc_corpus {commits,issues} mine --run-dir RUN` collects a run once, then
writes it. The stages below run per repository, largest repositories first. A
repository that fails is retried in up to three passes; one that still has gaps is
reported, never silently counted as complete.

## Inputs (`config/`)

- `repositories.json`: the 179 repositories, 50 curated by hand and 129 found by
  keyword search on GitHub, frozen on 23 September 2026.
- `corpus_policy.json`: 90 search terms (scheme names such as ML-KEM, Kyber, Dilithium
  and SPHINCS+; standards such as FIPS 203; generic terms such as post-quantum and
  liboqs) and the corpus cutoff 0.148. Five scheme names that are ordinary words
  (BIKE, Falcon, HAWK, MAYO, X-Wing) are left out because they match unrelated text.

A new run copies both into `RUN/` (`manifest.json`, and the policy as
`tier_policy.json`, the name the collector reads) and never replaces them; the
policy's SHA-256 is recorded, and every corpus plan must match it.

## Stages

1. **Corpus search** (`collector/corpus_search.ts`). GitHub search counts the repository's
   pull requests and issues that contain a term in their title, body or comments,
   six terms per query, merging the results. Its score is that count divided by all
   of its pull requests and issues.
   - **A**: score 0.148 or more. Every issue, pull request and commit is collected.
   - **B**: score below 0.148. Only issues and pull requests whose **title or body**
     contains a term are collected.
   - **C** (`unrated` inside the run): no pull requests or issues at all. Every commit
     is collected.

   A query with more than 1,000 results is split into smaller term sets, then into
   creation-time ranges. The plan (`tier_plans/`) records the score, the corpus and the
   selected issue and pull request numbers.
2. **GitHub API** (`collector/collect_api.ts`): the selected issues with all their
   comments, and the selected pull requests with their commit lists and the issues they
   close. Comments do not need to match a term: a selected item keeps its whole
   conversation. An issue that a selected pull request closes is not collected unless
   it was selected itself.
3. **Git history** (`collection/git_history`): a full `git clone --mirror`, frozen once
   its refs are recorded, and the metadata of every commit reachable from any ref
   (PyDriller). An independent `git rev-list --all --count` must agree.
4. **Commit-list recovery** (`collector/recover_commits.ts`): GitHub returns at most
   250 commits per pull request. A cut-short list is recorded as a failure and rebuilt
   from the mirror's base..head range, accepted only if it has the expected count and
   contains every SHA the API returned. Otherwise the gap stays recorded.
5. **Commit selection** (`collection/commit_selection.py`): every commit in corpora A and C.
   In corpus B, the union of commits whose message contains a term (a literal,
   case-insensitive match between non-alphanumeric boundaries, not GitHub search) and
   commits of a selected pull request. A pull request's commit that is missing from the
   mirror is fetched into a separate recovery mirror; the frozen mirror never changes.
6. **Eligibility** (`collection/eligibility.py`, `commits mine` only):
   `on_default_branch` from `git rev-list HEAD` in the frozen mirror; from GitHub's
   `associatedPullRequests` for each commit, `in_merged_pr` (a merged pull request of
   the same repository) and `pqc_in_linked_text` (a PQC term in the title or body of any
   associated pull request of the same repository, or of an issue it closes). Both can
   describe a corpus B pull request that was not selected; the texts are used only for
   this test and are not stored.

Then `mine` writes the file. Patches and changed files come from `git diff` against
the first parent (the empty tree for a root commit), with no rename detection, no
indent heuristic and complete binary patches.

## Run directory

| Path | Holds |
|---|---|
| `manifest.json`, `tier_policy.json` | frozen inputs |
| `tier_plans/`, `tier_search_cache/` | corpus decisions and the search evidence behind them |
| `github.sqlite` | stored GitHub objects, page checkpoints and failures |
| `git_sources/<repo>/` | each repository's mirror and full commit metadata |
| `mirrors/`, `recovery_mirrors/` | links to the frozen mirrors; objects fetched for pull requests |
| `git.sqlite` | the selected commits and why each was selected |
| `eligibility.sqlite` | the three eligibility observations per commit |
| `pipeline_status.json`, `pipeline_repositories.json`, `logs/` | progress and per-repository logs |

Names inside the run directory keep the word "tier" of the frozen run's format, which
predates "corpus": `tier_policy.json`, `tier_plans/`, a plan's `tier` key, and
selection reasons such as `all_tier_A`. The code and the dataset say corpus.

The pipeline holds `pipeline.lock`, so two collections never run on one directory. To
pause, send SIGTERM; it is forwarded to the running worker, which saves its
checkpoint first. Rerun the same command to resume.

## Limits

- Observations are as of collection time: later edits, deletions and renames on
  GitHub are not reflected. A repository renamed later keeps its requested name.
- In corpus B, a PQC discussion that names no term in its title or body is not collected.
- The corpus search and commit matching use the 90 collection terms; the filter uses a
  wider list (see `pqc_corpus/filters/terms.py`).
- Commits that exist on GitHub but in no fetched ref, and objects GitHub no longer
  serves, are not in the mirror and so not in the dataset.
