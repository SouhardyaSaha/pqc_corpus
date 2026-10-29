"""Patch ids, after German, Adams & Hassan (2016), and changed-line extraction.

German, D. M., Adams, B., & Hassan, A. E. (2016). Continuously mining distributed
version control systems: an empirical study of how Linux uses Git. Empirical
Software Engineering, 21(1), 260-299. doi:10.1007/s10664-014-9356-2

A patch id identifies a change independently of the commit that carries it: the
full patch with `index` lines removed and each hunk header's line numbers
replaced by `@@-@@` (the function context after it is kept), hashed with SHA-1.
The same change rebased, squashed or cherry-picked onto shifted code keeps its
patch id.
"""

import hashlib
import re

HUNK_HEADER = re.compile(rb"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", re.MULTILINE)


def patch_id(patch: bytes) -> str:
    lines = [line for line in patch.split(b"\n") if not line.startswith(b"index ")]
    return hashlib.sha1(HUNK_HEADER.sub(b"@@-@@", b"\n".join(lines))).hexdigest()


def changed_lines(patch: str) -> str:
    """The added and removed lines of a patch, without file headers."""
    return "\n".join(
        line for line in patch.splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    )


def content_hash(patch: bytes) -> str:
    """SHA-256 of the patch without `index` lines, which carry per-copy blob ids."""
    lines = [line for line in patch.split(b"\n") if not line.startswith(b"index ")]
    return hashlib.sha256(b"\n".join(lines)).hexdigest()
