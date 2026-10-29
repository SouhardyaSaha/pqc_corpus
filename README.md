# PQC-Corpus

PQC-Corpus is a dataset of the development history of 179 public GitHub repositories
about post-quantum cryptography (PQC), collected on 21–24 September 2026. This
repository holds the code that builds it, its schemas and its documentation; the
dataset card is [dataset_card/README.md](dataset_card/README.md).

| File | One line is | Full set | Filtered set |
|---|---|---:|---:|
| `commits` / `commits_filtered` | a commit, with its full patch | 114,361 | 47,729 |
| `issues` / `issues_filtered` | an issue, with its comments and closing pull requests | 5,713 | 5,687 |
| `pull_requests` | a pull request, with its commits, closed issues, comments and reviews | 11,919 | — |
| `repositories` | a repository, with its corpus and GitHub metadata | 179 | — |

Every record belongs to a **corpus**: A (81 repositories, everything collected), B (87,
only keyword-matching items) or C (11, commits only). The **full set** is everything
collected. The **filtered set** keeps one copy of each change that reached a project's
main history, without inherited fork history, non-PQC work in general-purpose
libraries, or housekeeping commits, and issues written by people rather than bots
([docs/FILTERING.md](docs/FILTERING.md)). Field meanings are in [SCHEMA.md](SCHEMA.md);
storage, JSON Schemas and examples are in [schemas/](schemas/README.md).

## Layout

```
pqc_corpus/            Python package: python -m pqc_corpus ...
  collection/          collect a run: corpus search, GitHub API, Git history, commit selection, eligibility
  export/              write a finished run as JSON Lines
  filters/             commit filter (eight steps) and issue filter
  release.py           check a release directory, split large files, write checksums
  figures.py           table 1 and figures 3-5 of the paper
collector/             Deno (TypeScript) GitHub collector and corpus search, run by the pipeline
config/                frozen inputs: the 179 repositories and the corpus policy (90 search terms)
dataset_card/          the dataset's README for Hugging Face
schemas/               JSON Schemas of the data files
docs/                  how collection and filtering work
tests/                 Python tests (collector tests are in collector/tests/)
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
- **`figures`** writes table 1 (CSV, Markdown, LaTeX) and the data of figures 3–5 as
  CSV from a release directory, and draws the figures as PDF when matplotlib is
  installed.
- Each written file gets a `.meta.json` beside it with its row count, SHA-256 and the
  name of the run it came from. No output records an absolute path.

On the frozen run (below):

```
commits mine        114,361   commits filter   47,729
issues mine           5,713   issues filter     5,687
pull_requests mine   11,919   repositories mine   179
```

## Setup

- Python 3.11 or later. Exporting, filtering and `release` use only the standard
  library; `figures` draws PDFs with matplotlib if it is installed.
- To collect a new run, you also need Git, [Deno](https://deno.com) 2 (its dependencies
  are pinned in `collector/deno.lock`), PyDriller
  (`pip install -r requirements.txt`), and GitHub tokens: copy `.env.example` to
  `.env` and set `GITHUB_TOKEN_1` (up to `GITHUB_TOKEN_10`). Tokens are never logged.
- Disk: the full commit file is about 28 GB, the filtered one about 14 GB, and a run's
  Git mirrors about 20 GB.

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
- `figures`, run on the release directory, gives table 1 and figures 3–5 of the paper.

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

## Tests

```bash
python -m unittest discover -s tests -v
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
