"""The tables of the SQLite edition and how each JSON field maps onto them.

Each dataset has one main table with a row per record, in file order (`rowid`). A list
field becomes a child table with the parent's key, a `position` in the list and one
column per item field; `pr_numbers` and `pr_urls`, which pair up item by item, share
one child table. The filtered sets hold the same records as the full sets, so they are
membership tables (`position` is the line order of the filtered file). Booleans are
stored as 0/1 and restored from the field kind.

A patch longer than SQLite's value limit (1,000,000,000 bytes) is stored in pieces in
`commit_patch_parts`, and its `patch_content` is NULL (the JSON field is never null).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    key: str
    column: str
    kind: str  # 'text', 'integer' or 'boolean'
    nullable: bool = False


@dataclass(frozen=True)
class ListOf:
    """A JSON list field (or lists that pair up item by item) stored as a child table."""
    keys: tuple[str, ...]
    table: str
    items: tuple[Field, ...]
    objects: bool  # True: one list of objects with `items` as fields; False: one scalar list per item


@dataclass(frozen=True)
class Table:
    dataset: str
    name: str
    key: tuple[Field, ...]
    fields: tuple[Field | ListOf, ...]  # every JSON key of a record, in record order


def text(key: str, column: str | None = None, nullable: bool = False) -> Field:
    return Field(key, column or key, 'text', nullable)


def integer(key: str, column: str | None = None, nullable: bool = False) -> Field:
    return Field(key, column or key, 'integer', nullable)


def boolean(key: str, column: str | None = None, nullable: bool = False) -> Field:
    return Field(key, column or key, 'boolean', nullable)


def link(prefix: str) -> tuple[Field, ...]:
    """The {repo, number, url} of a linked issue or pull request, renamed to avoid the parent's key."""
    return (text('repo', f'{prefix}_repo'), integer('number', f'{prefix}_number'), text('url', f'{prefix}_url'))


def comment() -> tuple[Field, ...]:
    return (text('author', nullable=True), text('created_at'), text('body'))


REPO = text('repo')
NUMBER = integer('number')
SHA = text('sha')
PATCH_LIMIT = 1_000_000_000
PATCH_PARTS = 'commit_patch_parts'

REPOSITORIES = Table('repositories', 'repositories', (REPO,), (
    REPO, text('corpus'), text('url'), text('description', nullable=True),
    ListOf(('topics',), 'repository_topics', (text('topics', 'topic'),), objects=False),
    boolean('is_fork'), text('language', nullable=True), integer('stars'), integer('forks'), text('created_at'),
    integer('github_pull_requests', nullable=True), integer('github_issues', nullable=True), integer('git_commits'),
    text('fetched_at'),
))

ISSUES = Table('issues', 'issues', (REPO, NUMBER), (
    REPO, text('corpus'), NUMBER, text('url'), text('title'), text('body', nullable=True), text('state'),
    text('state_reason', nullable=True), text('author', nullable=True), text('created_at'),
    text('closed_at', nullable=True),
    ListOf(('closed_by_prs',), 'issue_closing_pull_requests', link('pr'), objects=True),
    ListOf(('comments',), 'issue_comments', comment(), objects=True),
    text('fetched_at'),
))

PULL_REQUESTS = Table('pull_requests', 'pull_requests', (REPO, NUMBER), (
    REPO, text('corpus'), NUMBER, text('url'), text('title'), text('body', nullable=True), text('state'),
    boolean('draft'), boolean('merged'), text('author', nullable=True), text('created_at'),
    text('closed_at', nullable=True), text('merged_at', nullable=True), text('base_branch', nullable=True),
    text('head_branch', nullable=True),
    ListOf(('commit_shas',), 'pull_request_commits', (text('commit_shas', 'sha'),), objects=False),
    ListOf(('closes_issues',), 'pull_request_closed_issues', link('issue'), objects=True),
    ListOf(('comments',), 'pull_request_comments', comment(), objects=True),
    ListOf(('reviews',), 'pull_request_reviews', (
        text('author', nullable=True), text('state'), text('submitted_at', nullable=True),
        text('body', nullable=True)), objects=True),
    ListOf(('review_comments',), 'pull_request_review_comments', (
        text('author', nullable=True), text('created_at'), text('path', nullable=True),
        integer('line', nullable=True), text('body', nullable=True)), objects=True),
    text('fetched_at'),
))

COMMITS = Table('commits', 'commits', (REPO, SHA), (
    REPO, text('corpus'), SHA, text('url'), text('message'), text('author_name'), text('author_key'),
    text('authored_at'), text('committer_name'), text('committed_at'),
    ListOf(('parents',), 'commit_parents', (text('parents', 'parent_sha'),), objects=False),
    ListOf(('pr_numbers', 'pr_urls'), 'commit_pull_requests',
           (integer('pr_numbers', 'pr_number'), text('pr_urls', 'pr_url')), objects=False),
    boolean('on_default_branch'), boolean('in_merged_pr'), boolean('pqc_in_linked_text', nullable=True),
    ListOf(('changed_files',), 'commit_files', (
        text('path'), text('status'), integer('additions', nullable=True), integer('deletions', nullable=True),
        boolean('binary')), objects=True),
    integer('lines_added'), integer('lines_deleted'), text('patch_encoding'),
    text('patch_content', nullable=True), text('fetched_at'),
))

TABLES = (REPOSITORIES, ISSUES, PULL_REQUESTS, COMMITS)
# Filtered dataset -> the full table whose records it selects.
FILTERED = {'commits_filtered': COMMITS, 'issues_filtered': ISSUES}

SQL_TYPES = {'text': 'TEXT', 'integer': 'INTEGER', 'boolean': 'INTEGER'}


def column_sql(field: Field) -> str:
    return f'{field.column} {SQL_TYPES[field.kind]}{"" if field.nullable else " NOT NULL"}'


def key_columns(table: Table) -> str:
    return ', '.join(field.column for field in table.key)


def schema_sql() -> str:
    """CREATE statements for every table; indexes on links are added after loading."""
    statements = []
    for table in TABLES:
        scalars = [field for field in table.fields if isinstance(field, Field)]
        columns = ',\n    '.join(column_sql(field) for field in scalars)
        statements.append(f'CREATE TABLE {table.name} (\n    {columns},\n    PRIMARY KEY ({key_columns(table)})\n);')
        for child in table.fields:
            if isinstance(child, ListOf):
                statements.append(child_sql(table, child))
    statements.append(f'''CREATE TABLE {PATCH_PARTS} (
    repo TEXT NOT NULL,
    sha TEXT NOT NULL,
    part INTEGER NOT NULL,
    content TEXT NOT NULL,
    PRIMARY KEY (repo, sha, part),
    FOREIGN KEY (repo, sha) REFERENCES commits (repo, sha)
);''')
    for name, table in FILTERED.items():
        key = ', '.join(column_sql(field) for field in table.key)
        statements.append(f'''CREATE TABLE {name} (
    position INTEGER PRIMARY KEY,
    {key},
    UNIQUE ({key_columns(table)}),
    FOREIGN KEY ({key_columns(table)}) REFERENCES {table.name} ({key_columns(table)})
);''')
    statements.extend(EXTRA_SQL)
    return '\n\n'.join(statements) + '\n'


def child_sql(table: Table, child: ListOf) -> str:
    key = ',\n    '.join(column_sql(field) for field in table.key)
    items = ',\n    '.join(column_sql(field) for field in child.items)
    return f'''CREATE TABLE {child.table} (
    {key},
    position INTEGER NOT NULL,
    {items},
    PRIMARY KEY ({key_columns(table)}, position),
    FOREIGN KEY ({key_columns(table)}) REFERENCES {table.name} ({key_columns(table)})
);'''


EXTRA_SQL = (
    '''CREATE TABLE commit_removals (
    step INTEGER NOT NULL,
    name TEXT NOT NULL,
    repo TEXT NOT NULL,
    sha TEXT NOT NULL,
    reason TEXT NOT NULL,
    duplicates_sha TEXT
);''',
    '''CREATE TABLE issue_removals (
    repo TEXT NOT NULL,
    number INTEGER NOT NULL,
    author TEXT,
    url TEXT NOT NULL,
    reason TEXT NOT NULL
);''',
    '''CREATE TABLE commit_observations (
    repo TEXT NOT NULL,
    sha TEXT NOT NULL,
    on_default_branch INTEGER NOT NULL,
    in_merged_pr INTEGER NOT NULL,
    pqc_in_linked_text INTEGER,
    PRIMARY KEY (repo, sha)
);''',
    '''CREATE TABLE about (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);''',
)

INDEX_SQL = (
    'CREATE INDEX commit_pull_requests_by_pr ON commit_pull_requests (repo, pr_number);',
    'CREATE INDEX pull_request_commits_by_sha ON pull_request_commits (repo, sha);',
    'CREATE INDEX pull_request_closed_issues_by_issue ON pull_request_closed_issues (issue_repo, issue_number);',
    'CREATE INDEX issue_closing_pull_requests_by_pr ON issue_closing_pull_requests (pr_repo, pr_number);',
    'CREATE INDEX commits_by_corpus ON commits (corpus);',
    'CREATE INDEX commit_removals_by_commit ON commit_removals (repo, sha);',
)
