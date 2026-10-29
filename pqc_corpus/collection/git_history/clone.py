"""Clone a full Git mirror into a staging directory, then publish it."""

import os
from pathlib import Path
import shutil
import subprocess
import time

from ...interrupt import StopController

CLONE_TIMEOUT_SECONDS = 3600
POLL_SECONDS = 2


def _should_abort(stop: StopController, target: Path, minimum_free: int, started: float) -> bool:
    return (
        stop.requested
        or shutil.disk_usage(target.parent).free < minimum_free
        or time.monotonic() - started > CLONE_TIMEOUT_SECONDS
    )


def _terminate(child: subprocess.Popen) -> None:
    child.terminate()
    try:
        child.wait(timeout=20)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()


def clone(repo: str, target: Path, minimum_free: int, stop: StopController) -> None:
    """Mirror-clone `repo` into `target` without embedding credentials.

    A stop request, low disk space, or the one-hour limit aborts the clone and
    raises; the unfinished staging directory is discarded on the next attempt.
    """
    temporary = target.with_name(target.name + '.incomplete')
    # Only our unfinished staging directory is discarded; finished mirrors stay.
    if temporary.exists():
        shutil.rmtree(temporary)
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_LFS_SKIP_SMUDGE': '1'}
    started = time.monotonic()
    child = subprocess.Popen(
        ['git', '-c', 'credential.helper=', 'clone', '--mirror',
         f'https://github.com/{repo}.git', str(temporary)],
        env=env,
    )
    stop.child = child
    interrupted = False
    try:
        while child.poll() is None:
            if _should_abort(stop, target, minimum_free, started):
                interrupted = True
                _terminate(child)
                break
            time.sleep(POLL_SECONDS)
        if interrupted or child.returncode:
            raise RuntimeError(
                f'Clone incomplete (exit {child.returncode}); retry staging retained'
            )
        temporary.replace(target)
    finally:
        stop.child = None
