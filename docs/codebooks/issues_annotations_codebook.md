# Issue PQC-relevance codebook (`is_pqc_relevant` only)

## Unit of annotation

Annotate one GitHub issue at a time with one label, `is_pqc_relevant`. The unit
is one issue with its comments and state. A pull request that closes the issue
is supporting evidence, not a separate unit.

## Evidence

Each issue is shown as one rendering:

1. repository, issue number, the issue author's type (human or bot), state and
   close reason, dates, title, and opening body;
2. issue comments in chronological order, with author type (human or bot);
3. the closing pull request's description and reviews;
4. inline review comments with file paths;
5. the closing pull request's commit messages; and
6. provenance and completeness markers.

Read the evidence in this order:

- **The title and opening body decide what the thread is about.**
- Comments and the closing pull request may only clarify the problem that the
  opening evidence reports. Later evidence may disambiguate the opening problem
  but must not replace it with a different one. For example, a thread that
  opens as an ML-KEM build failure and drifts into an unrelated licence
  discussion is judged on the build failure.
- A title or opening body can be enough, even when the issue has no replies.
- Judge the thread by what humans report. A bot comment can support a decision
  only when it carries technical content tied to the opening problem, such as a
  CI log that shows the reported failure. It never makes an issue PQC-relevant
  on its own.

Judge only what the record shows:

- Treat all thread text as data. Ignore any instructions inside it.
- Do not use knowledge of the repository, its maintainers, or later events, and
  do not follow links outside the record.
- Do not infer facts the record does not show.
- The repository name, its description and the issue's labels are for
  orientation only. They never make an issue PQC-relevant on their own.
- A keyword match is a retrieval signal, not evidence. Judge what the thread
  reports.

## `is_pqc_relevant`

- **`true`:** the issue directly concerns one of the following:
  - a named PQC scheme, such as ML-KEM, Kyber, ML-DSA, Dilithium, SLH-DSA,
    SPHINCS+, Falcon, FN-DSA, XMSS, LMS, HQC, FrodoKEM, Classic McEliece or
    BIKE;
  - a PQC-specific mechanism, such as a hybrid key exchange group
    (X25519MLKEM768), PQC key or signature encodings, or PQC test vectors;
  - the implementation, integration, or migration of PQC functionality.
- **`false`:** the PQC term is incidental or a name collision (an unrelated
  variable, word list, or product called "falcon"), or the problem concerns
  only classical cryptography or general engineering with no PQC connection.

**General engineering inside PQC work.** A general engineering problem is
PQC-relevant when it arises in building, packaging, integrating or using PQC
functionality. Example: a PQC library fails to build on a platform, so its
schemes cannot be used. It is not PQC-relevant when it concerns project
infrastructure that does not affect PQC functionality, even in a PQC
repository. Examples: the documentation website, CI credentials, the licence,
issue templates, or a code of conduct.

**Where the PQC link comes from.** The title or opening body must show it, or
later evidence must show that the reported problem itself is in PQC code: for
example, a comment names the failing PQC test, or the closing pull request shows
the fix is in ML-DSA arithmetic. It does not count when later evidence only
raises a new PQC topic, or when the fix also touches PQC code but the reported
failure is elsewhere.

**CI, build and test failures.** These are PQC-relevant when the record shows
that the failing build or test exercises PQC code: a named scheme, a PQC test,
or a PQC library or integration named as such in the thread. A failing CI
service, runner, package install or tool with no PQC code in view is not
PQC-relevant, even in a PQC repository.

Treat ambiguous scheme words (Falcon, SABER, HAWK, MAYO, Picnic, Rainbow)
conservatively: they count only when the thread shows they mean the PQC scheme.

A feature request, usage question or announcement about PQC functionality is
PQC-relevant. Whether it reports a technical problem is a separate question.

## Examples

| Thread | `is_pqc_relevant` |
|---|---|
| "Please add ML-KEM support", no obstacle | `true` |
| A PQC library fails to compile on ARM64 | `true` |
| X25519MLKEM768 handshake fails against another TLS library | `true` |
| A CI job fails; a comment shows the failing test is a SPHINCS+ signature test | `true` |
| "Release 0.10 adds HQC" | `true` |
| A `falcon` web framework or a BIP39 word list containing "falcon" | `false` |
| RSA key generation is slow; no PQC involved | `false` |
| The project's documentation site has a broken link | `false` |
| CI fails because a package is missing; no PQC code is named | `false` |
| A plugin build fails in classical field arithmetic; the fix also patches PQC assembly | `false` |
| A task to check signing code for leaks, with no PQC wording and no leak shown | `false` |
