"""Opaque author keys: equal keys mean the same Git author e-mail address, without revealing it.

A key is HMAC-SHA256 of the address under a secret that only the dataset's
maintainers hold, so nobody can test whether a known address is in the data, as
they could with a plain hash. The secret is 32 random bytes in a file kept outside
the release and the code repository; it is never logged. Only its fingerprint
(`key_id`) is recorded, so two exports can be checked to use the same secret.
"""

import hashlib
import hmac
import os
from pathlib import Path
import secrets

SECRET_BYTES = 32


def create_secret(path: Path) -> None:
    """Write a new random secret, readable by its owner only; never replaces an existing one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'xb', opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        stream.write(secrets.token_bytes(SECRET_BYTES))


class AuthorKeys:
    def __init__(self, secret_file: Path) -> None:
        self.secret = secret_file.read_bytes()
        if len(self.secret) < SECRET_BYTES:
            raise ValueError(f'{secret_file} holds fewer than {SECRET_BYTES} bytes')

    def key(self, email: str | None) -> str:
        return hmac.new(self.secret, (email or '').encode('utf-8'), hashlib.sha256).hexdigest()

    @property
    def key_id(self) -> str:
        return hmac.new(self.secret, b'pqc-corpus author key id', hashlib.sha256).hexdigest()[:16]
