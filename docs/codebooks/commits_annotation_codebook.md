# Commit PQC-relevance codebook (`is_pqc_related` only)

## Unit of annotation

Annotate one `repository + commit_sha` record at a time with one label,
`is_pqc_related`. A keyword match is how the commit was retrieved, not evidence
that it concerns PQC.

Read evidence in this order:

1. the commit patch and changed paths;
2. the commit subject and message;
3. linked merged-PR title and body;
4. issues explicitly connected through the linked PR's closing relationship;
5. linked discussion only when available/needed to interpret the change.

Weigh the code diff over the commit-message framing. If prose claims work the
patch does not show, do not attribute that work to the commit. Do not use
outside knowledge of the repository or its history, and do not infer changes the
evidence does not show.

A keyword in a file name or message is not enough on its own; look at what the
change does. A file that is not modified says nothing about whether the
repository supports a scheme.

Repository descriptions and topic tags provide orientation only. Do not use them
to turn an unrelated commit into a PQC-related commit, and do not infer PQC
relevance from the repository's general purpose. Bot-authored commits are
annotated using the same rules as human-authored commits.

## `is_pqc_related`

- `true`: the commit directly changes, adds, removes, configures, tests,
  documents, benchmarks, packages, or discusses a named PQC scheme or a
  scheme-specific PQC mechanism.
- `false`: the match is lexical noise (for example a variable called `hss`, or
  a BIP39 word list containing "falcon"), concerns only classical cryptography
  or unrelated code, the commit is empty, or the available evidence does not
  connect the commit to a named PQC scheme. Generic project tooling (licence,
  CI, linters, tool or action versions) is `false` when it does not change how
  a scheme is built, linked, packaged or released, even in a repository that
  implements a PQC scheme.

Whitespace, formatting, comment, and rename changes to a scheme's own files
count as PQC-related. Treat ambiguous words such as Falcon, SABER, HAWK, and
MAYO conservatively.

## Change rules

- Build, linking, packaging and release changes for a scheme's package, such as
  a version bump of a package that provides the scheme, are PQC-related.
- A dependency-version bump is PQC-related only when evidence ties that bump to
  scheme support or behavior: the scheme's code, configuration, or tests change
  in the bump. Documentation-only changes inside the dependency do not count. A
  generic bump (hash library, CI action, build tool) is not PQC-related.
- Tests, interoperability vectors, build integration, and test-only prototypes
  for a scheme are PQC-related.
- Benchmark or test-harness changes are PQC-related when the harness actively
  runs a PQC scheme.
- Catalogues, comparison sites or tables, registries, lists and scanners are
  PQC-related when the change edits a scheme's listing, metadata, tags,
  descriptions or reference figures.
- Attack or cryptanalysis code against a scheme (for example the SIDH key
  recovery attack) is PQC-related.
- Renaming or moving a scheme's files is PQC-related.
- A merge commit inherits no label from its linked PR automatically. Inspect
  the actual diff represented by the commit (the first-parent patch). If that
  patch is empty, the commit is not PQC-related.
