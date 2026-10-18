import hashlib
from pathlib import Path

from . import __version__
from .records import ItemError


def source_digest() -> str:
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".json"):
            digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def require_release(version: str | None, source: str | None) -> None:
    if version is not None and version != __version__:
        raise ItemError(
            "installed personal runtime version differs; reinstall the "
            "selected plugin runtime"
        )
    if source is not None and source != source_digest():
        raise ItemError(
            "installed personal runtime source differs; reinstall the "
            "selected plugin runtime"
        )
