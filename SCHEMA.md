# PQC-Corpus schema

PQC-Corpus holds the commits, issues and pull requests of 179 public GitHub
repositories about post-quantum cryptography, collected on 21–24 September 2026. Each
file is JSON Lines: one record per line. Storage, JSON Schemas and full examples are
in [`schemas/`](schemas/README.md); how the files are built is in [README.md](README.md).

| File | One line is | Full set | Filtered set | Key |
|---|---|---:|---:|---|
| `commits` | a commit, with its full patch | 114,361 (about 28 GB) | 47,729 | `repo`, `sha` |
| `issues` | an issue, with its comments and closing pull requests | 5,713 | 5,687 | `repo`, `number` |
| `pull_requests` | a pull request, with its commits, closed issues, comments and reviews | 11,919 | — | `repo`, `number` |
| `repositories` | a repository, with its corpus and GitHub metadata | 179 | — | `repo` |

**Full and filtered set.** The full set (`commits`, `issues`) is everything collected.
The filtered set (`commits_filtered`, `issues_filtered`) has the same records and
fields, reduced by fixed rules: for commits, only work that reached the default branch
or a merged pull request, each change once, without inherited fork history, non-PQC
commits of general libraries, or housekeeping commits; for issues, without issues
opened by bots ([docs/FILTERING.md](docs/FILTERING.md)).

**Corpus.** Every record has `repo` (`owner/name`, as requested at collection time)
and `corpus`, the repository's corpus:

| Corpus | Repositories | Commits | Issues and pull requests |
|---|---:|---|---|
| A | 81 | every commit | every issue and pull request |
| B | 87 | commits whose message names a PQC term, and commits of pull requests whose title or body names one | those whose title or body names a PQC term |
| C | 11 | every commit | none (the repository has no issues or pull requests) |

**Links.** A commit's `pr_numbers` names the pull requests that contain it, and a pull
request's `commit_shas` lists its commits. A pull request's `closes_issues` and an
issue's `closed_by_prs` are the two sides of GitHub's "closes" relationship; the linked
issue can be in another repository or not collected.

**Joins.** Always use `repo` together with `sha` or `number`: SHAs and numbers repeat
across repositories, and an issue and a pull request of one repository never share a
number.

## commits

| Field | Meaning |
|---|---|
| `repo`, `corpus`, `sha`, `url` | repository, corpus, commit SHA, link to the commit on GitHub |
| `message`, `author_name`, `authored_at`, `committer_name`, `committed_at`, `parents` | Git data; more than one parent for a merge commit |
| `author_key` | opaque key of the author's e-mail address; equal keys mean the same address, but the address cannot be recovered or tested from it |
| `pr_numbers`, `pr_urls` | collected pull requests of the same repository that contain the commit, and their links; empty means no collected pull request contains it, not that it was pushed directly |
| `on_default_branch` | reachable from the repository's default branch when observed |
| `in_merged_pr` | GitHub associates it with a merged pull request of the same repository; can be true with empty `pr_numbers`, because corpus B collects only keyword-matching pull requests |
| `pqc_in_linked_text` | a PQC term appears in a pull request GitHub associates with it or in an issue such a pull request closes; `null` for commits on no default branch and in no merged pull request (not observed) |
| `changed_files` | `{path, status, additions, deletions, binary}` against the first parent; status A added, M modified, D deleted, T type changed; counts are `null` for binary files |
| `lines_added`, `lines_deleted` | totals over the text files |
| `patch_content` | full `git diff` against the first parent (the empty tree for a root commit), including binary changes |
| `patch_encoding` | `utf-8`, or `base64` when the patch is not valid UTF-8 |

## issues

| Field | Meaning |
|---|---|
| `repo`, `corpus`, `number`, `url` | repository, corpus, issue number, link to the issue on GitHub |
| `title`, `body`, `state`, `state_reason`, `author`, `created_at`, `closed_at` | GitHub data; `author` is `null` for a deleted account |
| `closed_by_prs` | `{repo, number, url}` of the pull requests that close the issue |
| `comments` | `{author, created_at, body}` in posting order |

## pull_requests

| Field | Meaning |
|---|---|
| `repo`, `corpus`, `number`, `url` | repository, corpus, pull request number, link on GitHub |
| `title`, `body`, `state`, `draft`, `merged`, `author` | GitHub data; `merged` is true if it was merged |
| `created_at`, `closed_at`, `merged_at` | times; `null` when it has not happened |
| `base_branch`, `head_branch` | the branch it targets and the branch it comes from |
| `commit_shas` | its commits, as GitHub lists them; all are in `commits` |
| `closes_issues` | `{repo, number, url}` of the issues it closes |
| `comments` | general discussion: `{author, created_at, body}` in posting order |
| `reviews` | formal reviews: `{author, state, submitted_at, body}`; state is APPROVED, CHANGES_REQUESTED, COMMENTED or DISMISSED |
| `review_comments` | inline comments on the diff: `{author, created_at, path, line, body}` |

## repositories

| Field | Meaning |
|---|---|
| `repo`, `corpus`, `url` | repository, corpus, link on GitHub |
| `description`, `topics`, `is_fork`, `language`, `stars`, `forks`, `created_at` | GitHub metadata |
| `github_pull_requests`, `github_issues` | GitHub's counts of all the repository's pull requests and issues when its corpus was assigned |
| `git_commits` | commits in the repository's full Git history before selection |

The commit filter reads `is_fork`, `description` and `topics`; table 1 and figures 3–4
of the paper read the rest.

Every record also has `fetched_at`, when it was observed; later edits on GitHub are
not included.

## Links checked

All 131,978 distinct commit, issue and pull-request links were checked against GitHub
on 28 October 2026, and 131,949 point to the same object at the same address. The 29
others:
- 11 `facebook/folly` links: GitHub moved the repository to `meta/folly` and redirects
  the old links there.
- 16 links of `zoahdev/kinegrant-protocol` (11 commits, 5 pull requests): the
  repository has since been deleted.
- 2 issues, `RustCrypto/KEMs#273` and `open-quantum-safe/liboqs-rust#266`, have
  been deleted.

Links are kept as collected. The records keep the text and patches, so deleted items
remain usable.

## Personal data

Usernames and Git author names are kept as published. E-mail addresses are not
included as fields: commits carry only `author_key`, a keyed hash made with a secret
that is not published, so a known address cannot be looked up in the data. E-mail
addresses written into messages, text or patches (for example `Signed-off-by` lines)
are unchanged.
