"""Persist advertised Git refs and mine commit metadata with PyDriller.

Mirrors are frozen once a refs snapshot is saved. Resume never silently fetches
new history. Full file contents/diffs remain recoverable from the local mirror.

Modules: `clone` (staged mirror clones), `commits` (refs snapshot, commit
metadata, completeness check), and `worker` (the resumable command).
"""

from .worker import main

__all__ = ['main']
