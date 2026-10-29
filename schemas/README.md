# PQC-Corpus storage and schemas

PQC-Corpus has four files: commits, issues, pull requests and repositories. Commits
and issues also have a filtered set with the same schema. Each file has a JSON Schema (draft 2020-12) in this
folder; field meanings are in each schema's `description` and in
[`../SCHEMA.md`](../SCHEMA.md).

## Layout

```
pqc-corpus/
├── README.md                     dataset card
├── SCHEMA.md                     field guide
├── schemas/                      this folder: <file>.schema.json for each file below
├── commits/                      full set: 114,361 commits, about 28 GB with their patches
│   ├── part-00000.jsonl
│   └── …                         (about 1 GB each)
├── commits_filtered/             filtered set: 47,729 commits, same schema
│   └── part-*.jsonl
├── issues.jsonl                  full set: 5,713 issues with their comments, about 26 MB
├── issues_filtered.jsonl         filtered set: 5,687 issues, same schema
├── pull_requests.jsonl           11,919 pull requests with their discussion and reviews, about 107 MB
├── repositories.jsonl            179 repositories
├── provenance/                   frozen_observations_2026-09-29.jsonl: the observations the commits were mined with
├── commits_filtered_report/      why each commit left the filtered set: one CSV per step
├── issues_filtered_report/       why each issue left the filtered set
├── manifest.json                 rows, bytes and SHA-256 of every data file
├── SHA256SUMS                    checksums of every file: sha256sum -c SHA256SUMS
└── LICENSE                       data licence (CC BY 4.0; record content under the source licences)
```

```
commits ◄──pr_numbers / commit_shas──► pull_requests ◄──closes_issues / closed_by_prs──► issues
   └──────────────────────────────────── repo ──────────────────────────────────────────┘
                                          ▼
                                    repositories
```

- Every record carries `repo` (`owner/name`) and `corpus` (A, B or C). Keys are `repo`
  with `sha` (commits) or `number` (issues), because SHAs and numbers repeat across
  repositories.
- A commit and an issue are linked through a pull request: one of the commit's
  `pr_numbers` is in the issue's `closed_by_prs` (same `repo`).
- Comments and reviews are stored inside their issue or pull request, in posting order.
- The commit files are split into parts only because of their size; read the parts of
  one folder as one file. Almost all of the size is `patch_content`.

## Format

- JSON Lines: one JSON object per line, UTF-8, `\n` line endings, not compressed.
- Every field listed in a schema is present in every record, in the schema's order; a
  value that does not apply is `null`.
- Lists are JSON arrays and nested records are JSON objects.
- Timestamps are ISO 8601 strings as GitHub or Git wrote them.
- Commits are ordered by `repo` and `sha`, issues and pull requests by `repo` and
  `number`, repositories by `repo`.

## Reading and checking

```python
import glob, json

def commits(folder="commits"):
    for path in sorted(glob.glob(f"{folder}/part-*.jsonl")):
        for line in open(path, encoding="utf-8"):
            yield json.loads(line)      # one at a time; some patches are very large

# issues closed by each pull request
closes = {}
for issue in map(json.loads, open("issues_filtered.jsonl", encoding="utf-8")):
    for pr in issue["closed_by_prs"]:
        closes.setdefault((pr["repo"], pr["number"]), []).append(issue)

for c in commits("commits_filtered"):
    issues = [i for n in c["pr_numbers"] for i in closes.get((c["repo"], n), [])]
```

```python
import json, jsonschema           # pip install jsonschema

validator = jsonschema.Draft202012Validator(json.load(open("schemas/issues.schema.json")))
for n, line in enumerate(open("issues.jsonl", encoding="utf-8"), 1):
    for error in validator.iter_errors(json.loads(line)):
        print(n, error.json_path, error.message)
```

## Examples

One real record per file: RustCrypto/KEMs issue #46, PR #47 that closes it, one of
that PR's commits, and the repository. In the files each record is one line; here it is
indented and shortened: strings longer than 160 characters end in `…`, lists show at
most two entries (full lengths are given above each example), and `patch_content` is
cut after 600 characters.


### `issues`

Issue #46 asks for an update to final FIPS 203. `closed_by_prs` names PR #47, which contains the commit below. Full list lengths: `comments` 5. Schema: [`issues.schema.json`](issues.schema.json).

```json
{
  "repo": "RustCrypto/KEMs",
  "corpus": "A",
  "number": 46,
  "url": "https://github.com/RustCrypto/KEMs/issues/46",
  "title": "ml-kem: update to FIPS 203 final",
  "body": "It's out: https://nvlpubs.nist.gov/nistpubs/fips/nist.fips.203.pdf\r\n\r\ncc @bifurcation \r\n\r\n> ### C.2 Changes From FIPS 203 Initial Public Draft\r\n>The differences…",
  "state": "closed",
  "state_reason": "completed",
  "author": "tarcieri",
  "created_at": "2024-08-13T14:48:50Z",
  "closed_at": "2024-08-16T20:00:32Z",
  "closed_by_prs": [
    {
      "repo": "RustCrypto/KEMs",
      "number": 47,
      "url": "https://github.com/RustCrypto/KEMs/pull/47"
    }
  ],
  "comments": [
    {
      "author": "tarcieri",
      "created_at": "2024-08-13T22:03:21Z",
      "body": "Looks like there was a mistake in the \"final\" spec:\r\n\r\nhttps://groups.google.com/a/list.nist.gov/d/msgid/pqc-forum/CO6PR09MB759124EB4EF0B2F7C961BC47F0862%40CO6P…"
    },
    {
      "author": "bifurcation",
      "created_at": "2024-08-16T20:10:05Z",
      "body": "@tarcieri This seems like it probably merits a version bump and new crate version?"
    }
  ],
  "fetched_at": "2026-09-21T18:36:40.452Z"
}
```

### `pull_requests`

PR #47, which closes issue #46. Full list lengths: `commit_shas` 5, `closes_issues` 1, `comments` 6, `reviews` 1, `review_comments` 0. Schema: [`pull_requests.schema.json`](pull_requests.schema.json).

```json
{
  "repo": "RustCrypto/KEMs",
  "corpus": "A",
  "number": 47,
  "url": "https://github.com/RustCrypto/KEMs/pull/47",
  "title": "ml-kem: Update to FIPS 203",
  "body": "Fixes #46 \r\n\r\nThis PR implements the two changes noted in Appendix C of [FIPS 203]:\r\n\r\n* Domain separation in K-PKE.KeyGen\r\n* Reversing the order of indices in …",
  "state": "closed",
  "draft": false,
  "merged": true,
  "author": "bifurcation",
  "created_at": "2024-08-15T16:19:27Z",
  "closed_at": "2024-08-16T20:00:31Z",
  "merged_at": "2024-08-16T20:00:31Z",
  "base_branch": "master",
  "head_branch": "fips-203",
  "commit_shas": [
    "56f104aecb60dbdf9b6cd1c2b8edcb2dc441782f",
    "6337c004cc66da56da118187e0ebbee731c85d51"
  ],
  "closes_issues": [
    {
      "repo": "RustCrypto/KEMs",
      "number": 46,
      "url": "https://github.com/RustCrypto/KEMs/issues/46"
    }
  ],
  "comments": [
    {
      "author": "tarcieri",
      "created_at": "2024-08-16T00:12:12Z",
      "body": "At some point the documentation (README.md, Cargo.toml) should also be updated to note it's no longer the draft construction"
    },
    {
      "author": "tarcieri",
      "created_at": "2024-08-16T14:48:27Z",
      "body": "Looks like new test vectors are available here:\r\n\r\n- https://github.com/usnistgov/ACVP-Server/tree/master/gen-val/json-files/ML-KEM-keyGen-FIPS203\r\n- https://gi…"
    }
  ],
  "reviews": [
    {
      "author": "tarcieri",
      "state": "APPROVED",
      "submitted_at": "2024-08-16T20:00:12Z",
      "body": ""
    }
  ],
  "review_comments": [],
  "fetched_at": "2026-09-21T18:36:36.466Z"
}
```

### `commits`

One of the five commits of PR #47 (`pr_numbers`), with its patch. PR #47 was merged (`in_merged_pr`); the commit itself is not on the default branch. It is in the filtered set. Schema: [`commits.schema.json`](commits.schema.json).

```json
{
  "repo": "RustCrypto/KEMs",
  "corpus": "A",
  "sha": "56f104aecb60dbdf9b6cd1c2b8edcb2dc441782f",
  "url": "https://github.com/RustCrypto/KEMs/commit/56f104aecb60dbdf9b6cd1c2b8edcb2dc441782f",
  "message": "Update documentation",
  "author_name": "Richard Barnes",
  "author_key": "…",
  "authored_at": "2024-08-16T11:16:07-04:00",
  "committer_name": "Richard Barnes",
  "committed_at": "2024-08-16T11:16:07-04:00",
  "parents": [
    "cc1bc83ad6c857d2dc575ec60c6fcf30001e68b0"
  ],
  "pr_numbers": [
    47
  ],
  "pr_urls": [
    "https://github.com/RustCrypto/KEMs/pull/47"
  ],
  "on_default_branch": false,
  "in_merged_pr": true,
  "pqc_in_linked_text": true,
  "changed_files": [
    {
      "path": "ml-kem/Cargo.toml",
      "status": "M",
      "additions": 1,
      "deletions": 1,
      "binary": false
    },
    {
      "path": "ml-kem/README.md",
      "status": "M",
      "additions": 2,
      "deletions": 2,
      "binary": false
    }
  ],
  "lines_added": 3,
  "lines_deleted": 3,
  "patch_encoding": "utf-8",
  "patch_content": "diff --git a/ml-kem/Cargo.toml b/ml-kem/Cargo.toml\nindex 7490cfe469bf3aa26fdb6c2774271ae75e0a5620..73d7a83ef66733a023e084b00218120e599056c5 100644\n--- a/ml-kem/Cargo.toml\n+++ b/ml-kem/Cargo.toml\n@@ -2,7 +2,7 @@\n name = \"ml-kem\"\n description = \"\"\"\n Pure Rust implementation of the Module-Lattice-Based Key-Encapsulation Mechanism Standard\n-(formerly known as Kyber) as described in the FIPS 203 Initial Public Draft\n+(formerly known as Kyber) as described in FIPS 203\n \"\"\"\n version = \"0.1.1\"\n edition = \"2021\"\ndiff --git a/ml-kem/README.md b/ml-kem/README.md\nindex 3d43ef232415d1aa4c87c89090f35510d0e3",
  "fetched_at": "2026-09-21T17:58:02.518251+00:00"
}
```

### `repositories`

The repository of the records above. Schema: [`repositories.schema.json`](repositories.schema.json).

```json
{
  "repo": "RustCrypto/KEMs",
  "corpus": "A",
  "url": "https://github.com/RustCrypto/KEMs",
  "description": "Collection of Key Encapsulation Mechanisms written in pure Rust",
  "topics": [],
  "is_fork": false,
  "language": "Rust",
  "stars": 111,
  "forks": 54,
  "created_at": "2023-08-16T14:17:12Z",
  "github_pull_requests": 337,
  "github_issues": 48,
  "git_commits": 773,
  "fetched_at": "2026-09-21T18:36:34.870Z"
}
```
