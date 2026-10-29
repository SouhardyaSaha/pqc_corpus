---
license: cc-by-4.0
pretty_name: PQC-Corpus
language:
- en
tags:
- software-engineering
- mining-software-repositories
- post-quantum-cryptography
- cryptography
- git
- github
size_categories:
- 100K<n<1M
configs:
- config_name: commits
  data_files: commits/part-*.jsonl
- config_name: commits_filtered
  data_files: commits_filtered/part-*.jsonl
- config_name: issues
  data_files: issues.jsonl
- config_name: issues_filtered
  data_files: issues_filtered.jsonl
- config_name: pull_requests
  data_files: pull_requests.jsonl
- config_name: repositories
  data_files: repositories.jsonl
---

# PQC-Corpus

PQC-Corpus is the development history of 179 public GitHub repositories about
post-quantum cryptography (PQC): their commits with full patches, their issues and
pull requests with discussions and reviews, and the repositories themselves. It
was collected on 21–24 September 2026.

| File | One line is | Rows | Size |
|---|---|---:|---:|
| `commits/` | a commit, with its full patch | 114,361 | about 28 GB |
| `commits_filtered/` | the filtered set of commits | 47,729 | about 14 GB |
| `issues.jsonl` | an issue, with its comments and closing pull requests | 5,713 | 26 MB |
| `issues_filtered.jsonl` | the filtered set of issues | 5,687 | 26 MB |
| `pull_requests.jsonl` | a pull request, with its commits, closed issues, comments and reviews | 11,919 | 107 MB |
| `repositories.jsonl` | a repository, with its corpus and GitHub metadata | 179 | 80 KB |

The commit folders hold parts of about 1 GB (`part-00000.jsonl`, ...); read them in
order as one file. `provenance/frozen_observations_2026-09-29.jsonl` holds the
29 September 2026 observations the commits were mined with (default branch, merged
pull request, PQC terms in linked pull requests), so the commit export can be rerun on
the frozen collection.

## Corpora

Every record has `repo` (`owner/name`) and `corpus`:

| Corpus | Repositories | What was collected |
|---|---:|---|
| A | 81 | every commit, issue and pull request; at least 14.8% of the repository's pull requests and issues name a PQC term |
| B | 87 | larger, general-purpose projects: only issues and pull requests whose title or body names a PQC term, and commits whose message names one or that belong to such a pull request |
| C | 11 | repositories with no issues or pull requests; every commit |

The 90 search terms include scheme names (ML-KEM, Kyber, Dilithium, SPHINCS+, ...),
standards (FIPS 203–206) and generic terms (post-quantum, liboqs).

## Filtered sets

The full sets are everything collected. The filtered sets are reduced by fixed,
scripted rules, with every removal listed in `commits_filtered_report/` and
`issues_filtered_report/`:

- **Commits:** only work that reached the default branch or a merged pull request;
  each change once (rebase, squash and merge copies removed); without history a fork
  inherited, commits with no PQC term in repositories not about PQC, and housekeeping
  commits (CI, lock files, repository metadata, bots).
- **Issues:** without the 26 issues opened by bot accounts.

## Using the data

```python
from datasets import load_dataset

issues = load_dataset("pqc-datasets/pqc-corpus", "issues_filtered", split="train")
commits = load_dataset("pqc-datasets/pqc-corpus", "commits_filtered", split="train", streaming=True)
```

Join on `repo` together with `sha` (commits) or `number` (issues, pull requests):
SHAs and numbers repeat across repositories. A commit's `pr_numbers` names the pull
requests that contain it; a pull request's `closes_issues` and an issue's
`closed_by_prs` link the two. `SCHEMA.md` describes every field, and `schemas/`
holds a JSON Schema per file. `manifest.json` lists every file's rows and SHA-256;
check the download with `sha256sum -c SHA256SUMS`.

## Limitations

- **Selection is by keyword.** A record in the dataset is not necessarily about PQC,
  and corpus B misses PQC work that names no term in a title, body or message.
- **Observations are as of collection.** Later edits, deletions and renames on GitHub
  are not reflected. Of 131,978 distinct links checked on 28 October 2026, 131,949
  point to the same object; one repository and two issues have since been deleted, and
  `facebook/folly` now redirects to `meta/folly`.
- **Counts reflect the selection policy, not adoption.** The corpora were selected
  differently, so pooled counts are not a measure of ecosystem-wide PQC activity.

## Personal data

Usernames and Git author names are kept as published on GitHub. E-mail addresses are
not included as fields; commits carry only `author_key`, a keyed hash of the author's
address made with a secret that is not published, so that copies of one commit can be
matched without a known address being testable against the data. Addresses written inside messages and patches, such as `Signed-off-by`
lines, are unchanged. Use the data for research on software development, not to
profile individuals.

## Licence

The dataset's selection, structure and documentation are licensed under CC BY 4.0.
The content of the records was written by the contributors of the source
repositories and remains under those repositories' licences; see `LICENSE`.

## Citation

If you use PQC-Corpus, please cite it. The DOI
[10.5281/zenodo.23784229](https://doi.org/10.5281/zenodo.23784229) always resolves to
the latest version; version 1.0.0 is
[10.5281/zenodo.23785041](https://doi.org/10.5281/zenodo.23785041).

```bibtex
@software{pqc_corpus_2026,
  author    = {Saha Dip, Souhardya and Fakorede, Moshood A. and Farooq, Umar},
  title     = {{PQC-Corpus: A Dataset of Post-Quantum Cryptography Development Artifacts on GitHub}},
  year      = {2026},
  publisher = {Zenodo},
  version   = {1.0.0},
  doi       = {10.5281/zenodo.23784229},
  url       = {https://doi.org/10.5281/zenodo.23784229}
}
```
