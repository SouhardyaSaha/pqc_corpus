"""Command line: `python -m pqc_corpus KIND ACTION ...`.

    commits mine         collect a run (if needed) and write every selected commit with its patch
    commits filter       reduce the mined commits to the filtered set
    issues mine          write every collected issue with its comments
    issues filter        reduce the mined issues to the filtered set
    pull_requests mine   write every collected pull request with its discussion and reviews
    repositories mine    write every repository with its corpus and GitHub metadata
    release              check a release directory, split large files into parts, write checksums
    figures              write table 1 and figures 3-5 of the paper from a release directory

`mine` prepares the run directory from `config/` when it is new and resumes an
unfinished collection; with `--no-collect` it only writes a finished run and
never contacts GitHub. An output path ending in `.jsonl` is one file; any other
path is a directory of parts of about 1 GB. Collection needs Deno, Git, PyDriller
and GitHub tokens (see README.md).
"""

import argparse
import os
from pathlib import Path
import sys

from .collection import eligibility
from .collection.github_client import GitHubGraphQL, load_tokens
from .collection.pipeline import collect, is_complete
from .collection.prepare import is_prepared, prepare
from .export import jsonl
from .export.author_key import AuthorKeys, create_secret
from .export.commits import commits
from .export.issues import issues
from .export.pull_requests import pull_requests
from .export.repositories import repositories
from .filters.commits import filter_commits
from .filters.issues import filter_issues

EXPORTS = {'commits': commits, 'issues': issues, 'pull_requests': pull_requests, 'repositories': repositories}


def ensure_collected(run: Path, allow_network: bool) -> None:
    """Prepare and collect the run unless it is already complete."""
    if is_prepared(run) and is_complete(run):
        return
    if not allow_network:
        raise SystemExit(f'{run} is not a finished run; rerun without --no-collect to collect it')
    if not is_prepared(run):
        prepare(run)
    code = collect(run)
    if code != 0:
        raise SystemExit(f'Collection stopped with exit code {code} (2: unresolved repositories, '
                         f'130: paused); see {run / "pipeline_repositories.json"}; rerun to resume')


def eligibility_observations(run: Path, given: Path | None, allow_network: bool) -> dict:
    if given:
        return eligibility.load(given)
    if allow_network:
        eligibility.observe(run, GitHubGraphQL(load_tokens()))
    database = run / 'eligibility.sqlite'
    if not database.exists():
        raise SystemExit(f'{run} has no eligibility observations; pass --eligibility or allow collection')
    return eligibility.load(database)


def mine(args: argparse.Namespace) -> None:
    run = args.run_dir.resolve()
    ensure_collected(run, not args.no_collect)
    # Provenance names the run and inputs, never their absolute paths.
    provenance = {'run': run.name}
    if args.kind == 'commits':
        observed = eligibility_observations(run, args.eligibility, not args.no_collect)
        provenance['eligibility'] = args.eligibility.name if args.eligibility else 'eligibility.sqlite'
        if not args.author_key_secret.exists():
            create_secret(args.author_key_secret)
            print(f'Created a new author-key secret at {args.author_key_secret}; keep it private and backed up')
        keys = AuthorKeys(args.author_key_secret)
        provenance['author_key_id'] = keys.key_id
        records = commits(run, observed, keys)
    else:
        records = EXPORTS[args.kind](run)
    rows = jsonl.write(args.output, records, **provenance)
    print(f'{args.output}: {rows} {args.kind}')


def report_dir(args: argparse.Namespace) -> Path:
    return args.report or args.output.with_name(args.output.name.removesuffix('.jsonl') + '_report')


def print_summary(summary: dict) -> None:
    print(f"mined {summary['mined']}")
    for step in summary['steps']:
        print(f"  {step['step']}. {step['name']}: -{step['removed']} -> {step['remaining']}")
    print(f"filtered {summary['filtered']}: {summary['output']['name']}")


def add_kind(kinds: argparse._SubParsersAction, kind: str, can_filter: bool) -> None:
    actions = kinds.add_parser(kind).add_subparsers(dest='action', required=True)
    mining = actions.add_parser('mine', help=f'write every collected record of a run as {kind}')
    mining.add_argument('--run-dir', type=Path, required=True, help='run directory (created if new)')
    mining.add_argument('--output', type=Path, required=True, help=f'{kind}.jsonl, or a directory for parts')
    mining.add_argument('--no-collect', action='store_true', help='never contact GitHub; the run must be finished')
    if kind == 'commits':
        mining.add_argument('--eligibility', type=Path,
                            help='recorded eligibility observations (JSONL) instead of observing them')
        mining.add_argument('--author-key-secret', type=Path, required=True,
                            help='secret file for author keys, outside the release (created if missing)')
    if not can_filter:
        return
    filtering = actions.add_parser('filter', help=f'write the filtered {kind}')
    filtering.add_argument('--input', type=Path, required=True, help=f'mined {kind} (file or directory of parts)')
    filtering.add_argument('--output', type=Path, required=True,
                           help=f'filtered {kind}.jsonl, or a directory for parts')
    filtering.add_argument('--report', type=Path, help='new directory for the removals (default: beside output)')
    if kind == 'commits':
        filtering.add_argument('--repositories', type=Path, required=True, help='repositories.jsonl from mine')
        filtering.add_argument('--workers', type=int, default=os.cpu_count() or 1,
                               help='processes that read the patches (default: one per CPU)')


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog='pqc_corpus', description=__doc__.split('\n\n')[0])
    kinds = top.add_subparsers(dest='kind', required=True)
    for kind in ('commits', 'issues', 'pull_requests', 'repositories'):
        add_kind(kinds, kind, can_filter=kind in ('commits', 'issues'))
    release = kinds.add_parser('release', help='check a release directory and write its checksums')
    release.add_argument('--dir', type=Path, required=True, help='directory holding the mined and filtered files')
    release.add_argument('--part-size', type=int, default=jsonl.PART_BYTES,
                         help='split single files larger than this many bytes into parts (default 1 GiB)')
    figures = kinds.add_parser('figures', help='write table 1 and figures 3-5 from a release directory')
    figures.add_argument('--dir', type=Path, required=True, help='release directory')
    figures.add_argument('--output', type=Path, required=True, help='new directory for the table and figures')
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.kind == 'release':
        from .release import release
        release(args.dir, args.part_size)
    elif args.kind == 'figures':
        from .figures import figures
        figures(args.dir, args.output)
    elif args.action == 'mine':
        mine(args)
    elif args.kind == 'commits':
        print_summary(filter_commits(args.input, args.repositories, args.output, report_dir(args), args.workers))
    else:
        print_summary(filter_issues(args.input, args.output, report_dir(args)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
