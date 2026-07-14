"""Single-process guard for the local BlueZ Mesh identities."""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO


class LockError(RuntimeError):
    pass


@contextmanager
def exclusive_runtime_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    old_umask = os.umask(0o077)
    handle: TextIO | None = None
    try:
        handle = path.open("a+", encoding="ascii")
        os.chmod(path, 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockError(
                "another SANlight Mesh command is already running; wait for it to finish"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n")
        handle.flush()
        yield
    finally:
        os.umask(old_umask)
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
