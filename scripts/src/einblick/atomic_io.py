from __future__ import annotations

import os
from pathlib import Path


def atomic_write_bytes(path: Path, body: bytes, mode: int = 0o600) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, mode)
    try:
        view = memoryview(body)
        while view:
            n = os.write(fd, view)
            if n <= 0:
                raise OSError("zero-byte write")
            view = view[n:]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    else:
        os.close(fd)
    os.replace(tmp, path)
