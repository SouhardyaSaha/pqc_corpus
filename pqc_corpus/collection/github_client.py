"""Minimal GitHub GraphQL client for the eligibility stage.

Tokens are read from `GITHUB_TOKEN_1` ... `GITHUB_TOKEN_10` in the environment or
the project `.env`, rotated per request, and never logged. Rate-limit and server
errors are retried with backoff; other errors are raised with the response
status only.
"""

import json
import os
from pathlib import Path
import time
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..paths import PROJECT_ROOT

GRAPHQL_URL = 'https://api.github.com/graphql'
MAX_ATTEMPTS = 6
TIMEOUT_SECONDS = 120


class GraphQL(Protocol):
    def query(self, text: str, variables: dict[str, Any]) -> dict[str, Any]: ...


def dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"\'')
    return values


def load_tokens(env_file: Path = PROJECT_ROOT / '.env') -> list[str]:
    values = {**dotenv(env_file), **os.environ}
    tokens = [values[f'GITHUB_TOKEN_{i}'] for i in range(1, 11) if values.get(f'GITHUB_TOKEN_{i}')]
    if not tokens:
        raise RuntimeError('No GitHub token: set GITHUB_TOKEN_1 in the environment or the project .env')
    return tokens


class GitHubGraphQL:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.next = 0

    def query(self, text: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({'query': text, 'variables': variables}).encode()
        for attempt in range(MAX_ATTEMPTS):
            token = self.tokens[self.next % len(self.tokens)]
            self.next += 1
            request = Request(GRAPHQL_URL, data=body, headers={
                'Authorization': f'bearer {token}', 'Content-Type': 'application/json'})
            try:
                with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                    data = json.load(response)
            except HTTPError as error:
                if error.code in (403, 429, 500, 502, 503, 504):
                    time.sleep(min(300, 15 * 2 ** attempt))
                    continue
                raise RuntimeError(f'GitHub GraphQL request failed with HTTP {error.code}') from None
            except (URLError, TimeoutError):
                time.sleep(min(300, 15 * 2 ** attempt))
                continue
            if data.get('errors') and not data.get('data'):
                messages = '; '.join(str(e.get('message', ''))[:200] for e in data['errors'])
                if 'rate limit' in messages.lower():
                    time.sleep(min(300, 15 * 2 ** attempt))
                    continue
                raise RuntimeError(f'GitHub GraphQL error: {messages}')
            return data['data']
        raise RuntimeError('GitHub GraphQL request failed after retries')
