# PQC-Corpus: SQLite edition

PQC-Corpus is the development history of 179 public GitHub repositories about
post-quantum cryptography (PQC), collected on 21–24 September 2026: their commits with
full patches, their issues and pull requests with discussions and reviews, and the
repositories themselves. This record holds release 1.0.0 (29 October 2026) as one
SQLite database, `pqc_corpus.db` (about 29 GB). The same release is on Hugging Face as
JSON Lines ([pqc-datasets/pqc-corpus](https://huggingface.co/datasets/pqc-datasets/pqc-corpus)),
and the code that collects and builds it is archived on Zenodo
([10.5281/zenodo.23784229](https://doi.org/10.5281/zenodo.23784229)).

Open it with any SQLite tool (the `sqlite3` shell, DB Browser for SQLite, Python's
`sqlite3`, DuckDB, ...); no server or import step is needed.

## Tables

One row per record:

| Table | Key | Rows |
|---|---|---:|
| `repositories` | `repo` | 179 |
| `issues` | `repo`, `number` | 5,713 |
| `pull_requests` | `repo`, `number` | 11,919 |
| `commits` | `repo`, `sha` | 114,361 |

A list inside a record is its own table, with the record's key, a `position` (0 is
the first item) and one column per item field:

| Table | Items | Rows |
|---|---|---:|
| `repository_topics` | GitHub topics: `topic` | 1,409 |
| `issue_comments` | comments in posting order: `author`, `created_at`, `body` | 16,473 |
| `issue_closing_pull_requests` | pull requests that close the issue: `pr_repo`, `pr_number`, `pr_url` | 2,002 |
| `pull_request_commits` | the pull request's commits: `sha` | 81,103 |
| `pull_request_closed_issues` | issues it closes: `issue_repo`, `issue_number`, `issue_url` | 2,110 |
| `pull_request_comments` | general discussion: `author`, `created_at`, `body` | 22,480 |
| `pull_request_reviews` | formal reviews: `author`, `state`, `submitted_at`, `body` | 37,648 |
| `pull_request_review_comments` | inline comments on the diff: `author`, `created_at`, `path`, `line`, `body` | 28,733 |
| `commit_parents` | `parent_sha`; more than one for a merge commit | 121,964 |
| `commit_pull_requests` | collected pull requests of the same repository that contain the commit: `pr_number`, `pr_url` | 81,103 |
| `commit_files` | files changed against the first parent: `path`, `status`, `additions`, `deletions`, `binary` | 1,245,776 |

And:

| Table | What it holds | Rows |
|---|---|---:|
| `commits_filtered` | keys of the filtered set of commits, in its order (`position`) | 47,729 |
| `issues_filtered` | keys of the filtered set of issues | 5,687 |
| `commit_removals` | every commit a filter step removed, with the step, its name and the reason | 66,632 |
| `issue_removals` | the issues opened by bot accounts | 26 |
| `commit_observations` | the 29 September 2026 observations the commits were mined with | 114,361 |
| `commit_patch_parts` | pieces of patches too large for one SQLite value (see below) | 5 |
| `about` | provenance: the JSON Lines release's checksums, meta files and filter summaries | 12 |

Field meanings are in the field guide,
[SCHEMA.md](https://github.com/SouhardyaSaha/pqc_corpus/blob/main/SCHEMA.md). Values are
as in the JSON Lines files, except:

- **Booleans** (`is_fork`, `draft`, `merged`, `on_default_branch`, `in_merged_pr`,
  `pqc_in_linked_text`, `binary`) are 0 or 1; NULL stays NULL.
- **Very large patches.** SQLite stores at most 1,000,000,000 bytes in one value. A
  patch above that has `patch_content` NULL and is stored in pieces in
  `commit_patch_parts`; read its rows in order of `part` and join them in your program.
  In this release that is one commit, `bcgit/bc-java` `5b34b18be12b` (about 1.2 GB of
  GeMSS test vectors), in 5 parts.
  `patch_encoding` is `base64` when the patch was not valid UTF-8.
- **Removal lists** come from the release's CSV files; an empty cell is NULL.

## Filtered sets

The filtered sets hold the same records as the full sets, so they are lists of keys.
Join them to the full tables:

```sql
SELECT c.*
FROM commits_filtered f
JOIN commits c ON c.repo = f.repo AND c.sha = f.sha
ORDER BY f.position;
```

The filters are fixed, scripted rules: for commits, only work that reached the default
branch or a merged pull request, each change once, without inherited fork history,
non-PQC commits of general-purpose libraries, or housekeeping commits; for issues,
without issues opened by bots.

## Joins and examples

Always join on `repo` together with `sha` or `number`: SHAs and numbers repeat across
repositories.

Commits of corpus A with the pull requests that contain them:

```sql
SELECT c.repo, c.sha, c.message, p.number, p.title
FROM commits c
JOIN commit_pull_requests cp ON cp.repo = c.repo AND cp.sha = c.sha
JOIN pull_requests p ON p.repo = cp.repo AND p.number = cp.pr_number
WHERE c.corpus = 'A';
```

From an issue to the code that closed it:

```sql
SELECT i.repo, i.number, i.title, pc.sha, c.message
FROM issues i
JOIN pull_request_closed_issues ci ON ci.issue_repo = i.repo AND ci.issue_number = i.number
JOIN pull_request_commits pc ON pc.repo = ci.repo AND pc.number = ci.number
JOIN commits c ON c.repo = pc.repo AND c.sha = pc.sha;
```

Reviews per state:

```sql
SELECT state, count(*) FROM pull_request_reviews GROUP BY state;
```

In Python:

```python
import sqlite3

db = sqlite3.connect("file:pqc_corpus.db?mode=ro", uri=True)
for repo, number, title in db.execute("SELECT repo, number, title FROM issues LIMIT 5"):
    print(repo, number, title)
```

## Corpora

Every main record has `corpus`:

| Corpus | Repositories | What was collected |
|---|---:|---|
| A | 81 | every commit, issue and pull request; at least 14.8% of the repository's pull requests and issues name a PQC term |
| B | 87 | larger, general-purpose projects: only issues and pull requests whose title or body names a PQC term, and commits whose message names one or that belong to such a pull request |
| C | 11 | repositories with no issues or pull requests; every commit |

## How it was checked

The database was built from the JSON Lines release by `python -m pqc_corpus database`.
The build rebuilt every line of every data file from the database and compared it with
the release byte for byte, and compared the removal lists and observations row by row;
it keeps the database only if all match. So the database holds exactly the release
whose checksums are in `about` (key `SHA256SUMS`).

## Limitations

- **Selection is by keyword.** A record is not necessarily about PQC, and corpus B
  misses PQC work that names no term in a title, body or message.
- **Records are as of collection.** Later edits, deletions and renames on GitHub are
  not reflected.
- **Counts reflect the selection policy, not adoption.** The corpora were selected
  differently, so pooled counts are not a measure of ecosystem-wide PQC activity.

## Personal data

Usernames and Git author names are kept as published on GitHub. Author e-mail
addresses are not included: commits carry only `author_key`, a keyed hash of the
address made with a secret that is not published. Addresses written inside messages
and patches, such as `Signed-off-by` lines, are unchanged. Use the data for research on
software development, not to profile individuals.

## Licence

The dataset's selection, structure and documentation are licensed under CC BY 4.0. The
content of the records was written by the contributors of the source repositories and
remains under those repositories' licences.

## Citation

```bibtex
@dataset{pqc_corpus_2026,
  author    = {Saha Dip, Souhardya and Fakorede, Moshood A. and Farooq, Umar},
  title     = {{PQC-Corpus: A Dataset of Linked Development Histories for Post-Quantum Cryptography}},
  year      = {2026},
  publisher = {Zenodo},
  version   = {1.0.0},
  doi       = {10.5281/zenodo.23890225},
  url       = {https://doi.org/10.5281/zenodo.23890225}
}
```
