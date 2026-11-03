# Scripts for working with a released dataset

These scripts read a published PQC-Corpus release. They do not collect data,
contact GitHub, or need tokens; the collection and export pipeline is the
`python -m pqc_corpus` CLI described in the [main README](../README.md).
They produce the traversal, audit, descriptive statistics, and figures reported in
the PQC-Corpus data paper.

Every script needs Python 3.11 or later and only the standard library, except the
three figure scripts, which also need matplotlib
(`python -m pip install -e '.[figures]'`). Run them from the repository root.

```text
scripts/
├── reuse/
│   ├── trace_issue.py              Follow an issue to its closing PRs and their commit patches
│   └── export_metadata.py          Build the patch-free view from the full release
├── validation/
│   ├── audit_dataset.py            Check hashes, schemas, keys, links, and removal ledgers
│   └── verify_metadata_release.py  Check an extracted patch-free view
├── analysis/
│   ├── characterize_coverage.py    Count PQC families and concerns named in PRs and issues
│   ├── characterize_dataset.py     Repository distributions and filtering effects, from an audit
│   └── characterize_timeline.py    PRs created per year and recorded GitHub inventories
├── figures/
│   ├── make_coverage.py            Bar chart of threads per family or concern
│   ├── make_activity.py            Quarterly threads per family, with NIST milestones
│   └── make_repositories.py        Box plots of repository characteristics by corpus
└── tests/                          Offline fixtures for trace_issue.py and export_metadata.py
```

## Which data each script reads

There are two ways to get the data:

- **Full release** (42.82 GB): the Hugging Face dataset
  [10.57967/hf/11329](https://doi.org/10.57967/hf/11329), pinned to revision
  `4d72fb06f0a9bcbf4d03412557255ea103e3109c`. Download it with Git LFS:

  ```bash
  GIT_LFS_SKIP_SMUDGE=1 git clone https://huggingface.co/datasets/pqc-datasets/pqc-corpus DATA
  git -C DATA checkout 4d72fb06f0a9bcbf4d03412557255ea103e3109c
  git -C DATA lfs pull
  (cd DATA && shasum -a 256 -c SHA256SUMS)
  ```

  A checkout can take about 86 GB with the LFS cache.
- **Patch-free view** (103.7 MB ZIP, 598.6 MB extracted): the archive in
  [`data/`](../data). It holds all six views without commit `patch_content`. Its
  issue, PR, and repository files are byte-identical to the full release.
  [Use the existing dataset](../README.md#use-the-existing-dataset) shows how to verify
  and extract it to `data/pqc-corpus-reviewer-metadata/`.

| Script | Full release | Patch-free view |
|---|:---:|:---:|
| `reuse/trace_issue.py` | yes | no (needs patches) |
| `reuse/export_metadata.py` | yes (the input) | no |
| `validation/audit_dataset.py` | yes | no |
| `validation/verify_metadata_release.py` | no | yes (the input) |
| `analysis/characterize_coverage.py` | yes | yes |
| `analysis/characterize_dataset.py` | yes, plus an audit report | yes, plus an audit report |
| `analysis/characterize_timeline.py` | yes | yes |
| `figures/make_repositories.py` | yes | yes |
| `figures/make_coverage.py`, `figures/make_activity.py` | reads `coverage.json` | reads `coverage.json` |

In the commands below, `DATA` is a full release checkout and `META` is
`data/pqc-corpus-reviewer-metadata`. Where both work, either can be passed to `--data`.

## Trace an issue to its patches

```bash
python3 scripts/reuse/trace_issue.py --data DATA --output trace-full.json
python3 scripts/reuse/trace_issue.py --data DATA --filtered --output trace-filtered.json
```

The script starts at an issue, follows its `closed_by_prs` links to the PRs, and
resolves each PR's `commit_shas` in the commit view. The default is
`RustCrypto/KEMs` issue 46, which leads to PR 47 and five commits. Choose another with
`--repo OWNER/NAME --issue NUMBER`. `--filtered` reads `commits_filtered` instead of
`commits` and lists any linked commit the filtered view does not contain.

The JSON output gives, for each commit, the shard and line it was read from, its
changed paths, and the SHA-256 and decoded size of its patch. Targets that were not
found are listed explicitly. For the default issue, both views resolve all five
commits, with 12 distinct paths and 1,489,674 patch bytes, and the patch hashes agree.

The reader scans records in 64 KiB chunks and hashes patch strings as it decodes them,
so memory stays small even though the largest released record is 1.2 GB. It stops
once every target is found. It relies on the published field order
(`repo`, `corpus`, then `sha` or `number`).

## Audit a release

```bash
python3 scripts/validation/audit_dataset.py DATA --output audit.json
```

This reads all six views (all 42.82 GB). The report's `validation` block has one
result per group of checks:

- `file_integrity_passed`: every file matches `SHA256SUMS` and the row count, size,
  and hash in `manifest.json`;
- `structural_checks_passed`: every record fits the four published JSON Schemas, using
  the keywords those schemas use (`type`, `required`, `properties`,
  `additionalProperties`, `items`, `enum`); keys are unique, dates parse, and line
  totals add up;
- `internal_links_passed`: every PR–commit link resolves and is recorded on both
  sides, and issue–PR closing links within the collection agree in both directions;
- `filter_ledgers_passed`: every filtered record is byte-identical to its full-view
  record, and the removal ledgers account for exactly the records that were removed;
- `frozen_observations_passed`: each commit has one observation in
  `provenance/frozen_observations_2026-09-29.jsonl`, and its three eligibility fields
  match the commit.

`all_checked_invariants_passed` combines the five. The audit does not rerun
the filters, and it does not judge whether a record is about PQC or whether its code is
correct. `--wait-for-files` audits hydrated shards first and waits for the rest, which
helps while `git lfs pull` is still running.

## Build and check the patch-free view

```bash
python3 scripts/reuse/export_metadata.py --data DATA --output reviewer-metadata
python3 scripts/validation/verify_metadata_release.py --metadata META --output metadata-check.json
```

`export_metadata.py` writes the patch-free view into a new, empty directory and never
changes the source. It reads all original data, but in bounded chunks. Each commit
keeps every field except `patch_content`, and gains:

- `_patch`: the encoding, decoded byte count, and SHA-256 of the patch;
- `_source`: the shard, line, byte offset, record length, and record SHA-256 in the
  original release.

The commit directories are named `commits_metadata/` and `commits_filtered_metadata/`,
so the view cannot be mistaken for input to the commit filters or to `trace_issue.py`.

`verify_metadata_release.py` checks the extracted view without the original patches. It
covers every checksum, JSON record, row count, and field set, the range of every
`_source` locator, and that full and filtered records agree. It does not do general
JSON Schema validation. Read `all_checks_passed` in the report.

The patch-free view keeps names and discussion text, so it is not anonymized. Full and
filtered views overlap; don't pool them as independent samples.

## Describe the dataset

```bash
python3 scripts/analysis/characterize_coverage.py --data META --output coverage.json
python3 scripts/analysis/characterize_timeline.py --data META --output timeline.json
python3 scripts/analysis/characterize_dataset.py --audit audit.json --data META --output characterization.json
```

- **`characterize_coverage.py`** counts PR and issue threads that name each PQC
  algorithm family (ML-KEM/Kyber, ML-DSA/Dilithium, SLH-DSA/SPHINCS+, FN-DSA/Falcon,
  HQC, Classic McEliece, FrodoKEM, XMSS/LMS) and three engineering concerns:
  hybrid key exchange, constant-time code and side channels, and known-answer tests. It reports counts by table, the number of
  repositories, and quarterly counts per family. Matching is case-insensitive on titles
  and bodies, after HTML comments and checklist questions left by PR templates are
  removed. Ambiguous names (Falcon, HAWK, MAYO, BIKE) count only with a parameter-set
  suffix. A thread can name several families. The counts are lexical mentions; they do
  not show that a project adopted or implemented an algorithm.
- **`characterize_timeline.py`** counts PRs by year of creation and totals the GitHub
  inventories recorded for each repository before selection. The 2026 count runs to
  24 September. Inventories and exported records come from different collection
  stages, so their ratio does not measure recall.
- **`characterize_dataset.py`** reads a finished `audit.json` and `repositories.jsonl`.
  It reports per-repository size distributions over all 179 repositories, zeros
  included, and again over only the repositories present in each view. It also reports
  the top-five share of each view, how many records have discussion text, and how many
  complete issue–PR–commit paths survive filtering. Quartiles use linear interpolation
  at (n−1)p. It does not rescan the large commit files.

## Draw the figures

```bash
python3 scripts/figures/make_coverage.py --coverage coverage.json --output fig-coverage.pdf
python3 scripts/figures/make_activity.py --coverage coverage.json --output fig-activity.pdf
python3 scripts/figures/make_repositories.py --data META --output fig-repositories.pdf
```

The coverage and activity figures are drawn from `coverage.json`. The activity figure
shows ML-KEM, ML-DSA, SLH-DSA, and hybrid key exchange from 2018 through the partial
third quarter of 2026. Numbered markers show NIST milestones. The
repository figure shows stars, forks, age, Git commits, and GitHub PR and issue
inventories as recorded at collection. Corpus C has no PRs or issues, so it is left out
of those two panels. Each output defaults to its file name in the current directory.

## Tests

```bash
python3 -m unittest discover -s scripts/tests -v
```

The 19 fixture tests build small JSONL files and run without the dataset. Five cover
`trace_issue.py`. Fourteen cover `export_metadata.py`, including patch encodings, byte
offsets, malformed input, and a memory bound on the chunked reader.
