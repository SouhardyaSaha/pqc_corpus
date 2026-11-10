# PQC-Corpus

## Contents

- [Overview](#overview)
- [Repository Layout](#repository-layout)
- [Commands](#commands)
- [Setup](#setup)
  - [Use the existing dataset](#use-the-existing-dataset)
  - [Use the Hugging Face dataset](#use-the-hugging-face-dataset)
  - [Use the Zenodo dataset](#use-the-zenodo-dataset)
  - [Set up the Python CLI](#set-up-the-python-cli)
  - [Set up data collection](#set-up-data-collection)
- [Collecting a run](#collecting-a-run)
- [Reproducing the released dataset](#reproducing-the-released-dataset)
- [Working with a release](#working-with-a-release)
- [Relevance labels](#relevance-labels)
- [Tests](#tests)
- [Licence](#licence)
- [Citation](#citation)

## Overview

PQC-Corpus is a dataset of the development history of 179 public GitHub repositories
about post-quantum cryptography (PQC), collected on 21–24 September 2026. This
repository holds the code that builds it, its schemas and its documentation; the
dataset card is [dataset_card/README.md](dataset_card/README.md). The dataset itself is
on Zenodo ([10.5281/zenodo.23890224](https://doi.org/10.5281/zenodo.23890224)) and
Hugging Face ([pqc-datasets/pqc-corpus](https://huggingface.co/datasets/pqc-datasets/pqc-corpus)),
and the paper that describes it is on arXiv
([10.48550/arXiv.2611.10966](https://doi.org/10.48550/arXiv.2611.10966)).

The [patch-free dataset](data/pqc-corpus-reviewer-metadata-4d72fb0.zip)
(103.7 MB ZIP; 598.7 MB extracted) preserves all six views and all fields except
commit patch contents, retaining patch hashes and source locations. Derived from
Hugging Face source revision [4d72fb0](https://huggingface.co/datasets/pqc-datasets/pqc-corpus/tree/4d72fb06f0a9bcbf4d03412557255ea103e3109c);
[SHA-256 checksum](data/pqc-corpus-reviewer-metadata-4d72fb0.zip.sha256).

| File | One line is | Full set | Filtered set |
|---|---|---:|---:|
| `commits` / `commits_filtered` | a commit, with its full patch | 114,361 | 47,729 |
| `issues` / `issues_filtered` | an issue, with its comments and closing pull requests | 5,713 | 5,687 |
| `pull_requests` | a pull request, with its commits, closed issues, comments and reviews | 11,919 | — |
| `repositories` | a repository, with its corpus and GitHub metadata | 179 | — |

Every record belongs to a **corpus**: A (81 repositories, everything collected), B (87,
only keyword-matching items) or C (11, commits only);
[docs/CORPORA.md](docs/CORPORA.md) lists the repositories in each. The **full set** is everything
collected. The **filtered set** keeps one copy of each change that reached a project's
main history, without inherited fork history, non-PQC work in general-purpose
libraries, or housekeeping commits, and issues written by people rather than bots
([docs/FILTERING.md](docs/FILTERING.md)). Field meanings are in [SCHEMA.md](SCHEMA.md);
storage, JSON Schemas and examples are in [schemas/](schemas/README.md).

## Repository Layout

```text
.
├── data/                  Patch-free dataset ZIP and SHA-256 checksum
├── pqc_corpus/            Python CLI: python -m pqc_corpus
│   ├── collection/       Run orchestration, Git history, selection, and eligibility
│   ├── export/           JSONL exporters for completed collection runs
│   ├── filters/          Eight-step commit filtering and bot-issue filtering
│   ├── release.py        Release validation, sharding, manifests, and checksums
│   ├── database/         SQLite edition, rebuilt and checked against the release
│   └── figures.py        Corpus summaries, repository profiles, and annual PR counts
├── collector/            Deno/TypeScript GitHub collector
│   ├── api/              API retrieval, pagination, and recovery
│   ├── search/           Repository classification and keyword search
│   ├── lib/              Shared GitHub transport, token rotation, and utilities
│   ├── tests/            Collector tests and fixtures
│   ├── deno.json         Deno configuration
│   └── deno.lock         Locked collector dependencies
├── config/               Frozen repository list and 90-term selection policy
├── dataset_card/         Dataset README distributed with the Hugging Face release
├── schemas/              Four JSON Schemas and record examples
├── scripts/              Offline traversal, audit, statistics, and paper figures for a release
├── docs/                 Collection procedures, filtering rules, limitations, repositories by corpus, and the SQLite edition
├── tests/                Python tests and fixtures
├── SCHEMA.md             Field definitions and relationship semantics
├── pyproject.toml        Python package, CLI entry point, and optional dependencies
├── requirements.txt      Collection, plotting, and schema-validation dependencies
├── .env.example          Template for local GitHub token configuration
├── CITATION.cff          Software citation metadata
├── .zenodo.json          Zenodo archival metadata
├── LICENSE               MIT license for the code
└── LICENSE-DATA          Dataset licensing scope and upstream-content boundaries
```

## Commands

```bash
python -m pqc_corpus commits       mine   --run-dir RUN --output out/commits --author-key-secret SECRET
python -m pqc_corpus issues        mine   --run-dir RUN --output out/issues.jsonl
python -m pqc_corpus pull_requests mine   --run-dir RUN --output out/pull_requests.jsonl
python -m pqc_corpus repositories  mine   --run-dir RUN --output out/repositories.jsonl
python -m pqc_corpus commits       filter --input out/commits --repositories out/repositories.jsonl \
                                          --output out/commits_filtered
python -m pqc_corpus issues        filter --input out/issues.jsonl --output out/issues_filtered.jsonl
python -m pqc_corpus release --dir out
python -m pqc_corpus database --dir out --output pqc_corpus.db
python -m pqc_corpus figures --dir out --output figures
```

- **`mine`** prepares `RUN` from `config/` if it is new, collects it (resumable: rerun
  the same command after an interruption), and writes the file. All four `mine`
  commands share one run, which is collected once. With `--no-collect` they only write
  a finished run and never contact GitHub. `commits mine` needs `--author-key-secret`, a
  file with the secret behind `author_key` (created with 32 random bytes if missing).
  Keep it private, outside the release and this repository, and back it up: the same
  secret gives the same keys in a later export.
- **Files or parts.** An output ending in `.jsonl` is one file; any other path is a
  directory of parts of about 1 GB (`part-00000.jsonl`, ...). Inputs can be either.
  Writing the commits as parts directly avoids needing room for a second copy.
- **`filter`** writes the kept lines unchanged, plus a report directory
  (`<output>_report/`): one CSV per step listing each removed record and why, and
  `summary.json` with the counts and the SHA-256 of every input and output.
- **`release`** checks every file's row count, splits any single file over 1 GB into
  parts, copies in the dataset card, field guide, schemas and data licence, and writes
  `manifest.json` and `SHA256SUMS` (check with `sha256sum -c SHA256SUMS`).
- **`database`** writes every dataset, the removal lists and the commit observations of
  a release directory into one SQLite file (tables in
  [docs/DATABASE.md](docs/DATABASE.md)). It then rebuilds every data file from the
  database and keeps the database only if each line matches the release byte for byte.
  It needs free space for the database (about 29 GB for the frozen run).
- **`figures`** reads a release directory and writes a per-corpus summary table
  (`table1.csv`, `.md`, `.tex`) and the data behind three figures as CSV: languages and
  commits per repository (`fig3*`), repository profiles (`fig4`), and pull requests per
  year (`fig5`). It draws the figures as PDF when matplotlib is installed. These outputs
  come from an earlier draft of the data paper; the paper's current figures come from
  [`scripts/`](scripts/README.md).
- Each written file gets a `.meta.json` beside it with its row count, SHA-256 and the
  name of the run it came from. No output records an absolute path.

On the frozen run (below):

```
commits mine        114,361   commits filter   47,729
issues mine           5,713   issues filter     5,687
pull_requests mine   11,919   repositories mine   179
```

## Setup

Run the following commands from the repository root on macOS or Linux (WSL on
Windows). Shell examples use Bash/Zsh; the CLI requires POSIX file locking.

### Use the existing dataset

The patch-free archive can be used without GitHub tokens or collection tools.
Verify and extract it:

```bash
cd data
shasum -a 256 -c pqc-corpus-reviewer-metadata-4d72fb0.zip.sha256
unzip pqc-corpus-reviewer-metadata-4d72fb0.zip
cd ..
```

On Linux, `sha256sum -c` can replace `shasum -a 256 -c`. The extracted
`data/pqc-corpus-reviewer-metadata/README.txt` explains its JSONL views, schemas,
and patch locators. Use the full Hugging Face snapshot linked above for patch
analysis and reproducing the commit filters.

### Use the Hugging Face dataset

The full release, patches included, loads with the `datasets` library
(`python -m pip install datasets`). Each file is a config: `commits`,
`commits_filtered`, `issues`, `issues_filtered`, `pull_requests` and `repositories`.
Pin the revision the paper describes, and stream the commit configs, which are about
28 GB and 14 GB:

```python
from datasets import load_dataset

revision = "4d72fb06f0a9bcbf4d03412557255ea103e3109c"
issues = load_dataset("pqc-datasets/pqc-corpus", "issues_filtered", split="train", revision=revision)
commits = load_dataset("pqc-datasets/pqc-corpus", "commits_filtered", split="train",
                       revision=revision, streaming=True)
```

Join records on `repo` together with `sha` or `number`, since SHAs and numbers repeat
across repositories. To download the files themselves (42.82 GB) and check them
against `SHA256SUMS`, see [scripts/README.md](scripts/README.md#which-data-each-script-reads).

### Use the Zenodo dataset

Zenodo ([10.5281/zenodo.23890224](https://doi.org/10.5281/zenodo.23890224)) holds the
same release as one SQLite database, `pqc_corpus.db` (28.46 GB). Download it and check
its MD5 (`md5sum` on Linux):

```bash
curl -L -o pqc_corpus.db "https://zenodo.org/records/23890225/files/pqc_corpus.db?download=1"
md5 pqc_corpus.db   # d23a44499064422d148b1d503758785f
```

Open it with any SQLite tool; no import step is needed. For example, from issue 46 of
`RustCrypto/KEMs` to the commits of the pull request that closed it:

```bash
sqlite3 "file:pqc_corpus.db?mode=ro" "
SELECT ci.number, c.sha, c.message
FROM issues i
JOIN pull_request_closed_issues ci ON ci.issue_repo = i.repo AND ci.issue_number = i.number
JOIN pull_request_commits pc ON pc.repo = ci.repo AND pc.number = ci.number
JOIN commits c ON c.repo = pc.repo AND c.sha = pc.sha
WHERE i.repo = 'RustCrypto/KEMs' AND i.number = 46;"
```

[docs/DATABASE.md](docs/DATABASE.md) lists the tables and how they differ from the JSON
Lines files.

### Set up the Python CLI

Use **Python 3.11 or later**; check with `python3 --version` before creating the
environment. An editable install keeps the CLI alongside `config/` and `collector/`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pqc_corpus --help
```

Exporting completed runs, filtering, release packaging, and `database` use
Python's standard library; exporting commit patches also requires Git. Install
optional Python dependencies for the tasks you need:

```bash
python -m pip install -e '.[collect]'   # PyDriller and Git-history dependencies
python -m pip install -e '.[figures]'   # matplotlib for PDF figures
python -m pip install -e '.[test]'      # JSON Schema validation in tests
```

For all three, use `python -m pip install -e '.[collect,figures,test]'`.

### Set up data collection

Install **Git**, **[Deno](https://deno.com) 2**, and the **`flock` command**, add
them to `PATH`, and install the `collect` dependencies above. macOS requires
installing `flock` separately. Check the executables:

```bash
git --version
deno --version
command -v flock
```

Copy `.env.example` to `.env` if you have not configured it already. Set
`GITHUB_TOKEN_1` to a GitHub token with read access to the public repositories;
optional additional tokens use `GITHUB_TOKEN_2` through `GITHUB_TOKEN_10`.
Both collectors read the repository's `.env` or process environment. Keep token
values private; `.env` is excluded from Git. Deno dependencies are locked in
`collector/deno.lock` and downloaded on first use.

Then use the [`mine` commands](#commands) with a shared `--run-dir`. The full
release occupies 42.82 GB; fresh collection also needs space for Git mirrors,
API databases, and intermediate outputs. Set `--run-dir` and `--output` to a
volume with sufficient space. The bundled metadata needs approximately 703 MB
for its ZIP and extracted files together.

## Collecting a run

`mine` runs, for each repository in `config/repositories.json`:

1. **Corpus search** (GitHub search): the share of the repository's pull requests and
   issues that name one of the 90 PQC terms decides its corpus. A: 14.8% or more, so
   every commit, issue and pull request is collected. B: below 14.8%, so only
   keyword-matching items are collected. C: no pull requests or issues, so every commit
   is collected.
2. **GitHub API**: the selected issues and pull requests, with their comments, reviews,
   commit lists and closing links.
3. **Git history**: a full mirror of the repository, frozen once cloned, and the
   metadata of every commit reachable from its refs.
4. **Commit-list recovery**: pull-request commit lists that GitHub cut short at 250
   commits are rebuilt from the mirror, and kept only if they match GitHub's count.
5. **Commit selection**: every commit in corpora A and C. In corpus B, commits whose
   message names a PQC term and commits of a selected pull request.
6. **Eligibility** (`commits mine` only): for each selected commit, whether it is on
   the default branch, whether GitHub associates it with a merged pull request, and
   whether the pull requests GitHub associates with it, or the issues they close, name
   a PQC term. The commit filter reads these three facts.

Details, limits and the run directory layout are in [docs/COLLECTION.md](docs/COLLECTION.md).

## Reproducing the released dataset

The released files were mined from the frozen run of 21–24 September 2026. GitHub has
changed since then, so a new run gives different numbers. For example, one corpus B
repository (`zoahdev/kinegrant-protocol`) has since been deleted, two collected issues
are gone, and `facebook/folly` is now `meta/folly`. The released files are therefore
the reference data:

- the commit filter, rerun on the released `commits` and `repositories`, and the issue
  filter, rerun on the released `issues`, give the released filtered sets exactly;
- `figures`, run on the release directory, gives the same summary table and figure data
  on every run.

## Working with a release

[`scripts/`](scripts/README.md) holds standalone scripts that read a published release
offline, with no GitHub access: an issue-to-patch traversal, the release audit, the
patch-free exporter and its verifier, descriptive statistics, and the data paper's
figures. Most of them also run on the patch-free view.

```bash
python3 scripts/reuse/trace_issue.py --data DATA --repo RustCrypto/KEMs --issue 46 --output trace.json
python3 scripts/validation/audit_dataset.py DATA --output audit.json
python3 scripts/analysis/characterize_coverage.py --data data/pqc-corpus-reviewer-metadata
```

Replace `DATA` with the path of your local clone of the full Hugging Face release (for
example `./data`); [scripts/README.md](scripts/README.md) shows how to
download it and says which scripts also run on the patch-free view.

The commits were mined from the frozen run with the eligibility observations made on
29 September 2026, published with the dataset as
`provenance/frozen_observations_2026-09-29.jsonl` (one line per commit with
`on_default_branch`, `in_merged_pr` and `pqc_in_linked_text`). The secret behind
`author_key` is not published, so an export by anyone else has different keys but the
same equalities:

```bash
python -m pqc_corpus commits mine --run-dir FROZEN_RUN --no-collect \
    --eligibility provenance/frozen_observations_2026-09-29.jsonl \
    --author-key-secret SECRET --output out/commits
```

## Relevance labels

Two annotators labelled 100 commits and 100 issues as PQC-related or not.
[docs/workbooks/](docs/workbooks) holds their labels and the adjudicated label for each
disagreement, and [docs/codebooks/](docs/codebooks) the labelling rules.
`scripts/annotation_agreement.py` (needs `openpyxl`) reports Cohen's kappa and the
share of PQC-related records:

```bash
python3 scripts/annotation_agreement.py commits docs/workbooks/commits_annotations_adjudicated.xlsx
python3 scripts/annotation_agreement.py issues docs/workbooks/issues_annotations_adjudicated.xlsx
```

Optionally, add `--release` with the full release or the extracted patch-free view
(for example `--release data/pqc-corpus-reviewer-metadata`) before the subcommand. The
workbooks do not record corpora, so the script reads from the release each labelled
record's corpus and which labelled commits are in the filtered view. It then also
reports the share per corpus and, for commits, for the filtered view.

The samples were not drawn at random from the release, so these shares describe the
labelled records only. They are not estimates for the whole corpus.

## Tests

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s scripts/tests -v
deno test --config collector/deno.json -A collector/tests
```

The tests use local fixtures (small Git repositories and SQLite databases) and never
contact GitHub. The Git-history test needs PyDriller and the schema test needs
`jsonschema`; each is skipped when its package is absent.

## Licence

Code: MIT ([LICENSE](LICENSE)). Data: CC BY 4.0 for the dataset's selection,
structure and documentation; the content of the records stays under the licences of
the source repositories ([LICENSE-DATA](LICENSE-DATA)).

## Citation

If you use PQC-Corpus, please cite the paper
([10.48550/arXiv.2611.10966](https://doi.org/10.48550/arXiv.2611.10966)):

```bibtex
@misc{pqc_corpus_paper_2026,
  author        = {Saha Dip, Souhardya and Fakorede, Moshood A. and Farooq, Umar},
  title         = {{PQC-Corpus: A Dataset of Linked Development Histories for Post-Quantum Cryptography}},
  year          = {2026},
  eprint        = {2611.10966},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CR},
  doi           = {10.48550/arXiv.2611.10966},
  url           = {https://doi.org/10.48550/arXiv.2611.10966}
}
```

and the dataset ([10.5281/zenodo.23890224](https://doi.org/10.5281/zenodo.23890224)):

```bibtex
@dataset{pqc_corpus_2026,
  author    = {Saha Dip, Souhardya and Fakorede, Moshood A. and Farooq, Umar},
  title     = {{PQC-Corpus: A Dataset of Linked Development Histories for Post-Quantum Cryptography}},
  year      = {2026},
  publisher = {Zenodo},
  version   = {1.0.0},
  doi       = {10.5281/zenodo.23890224},
  url       = {https://doi.org/10.5281/zenodo.23890224}
}
```
