import hashlib
import json
import re
from pathlib import Path

from tj_work_items.fingerprint import source_digest as shared_source_digest
from tj_work_items.records import ItemError

from . import __version__


def source_digest() -> str:
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".json"):
            digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def require_shared_runtime() -> None:
    manifest = json.loads(
        (Path(__file__).parent / "shared_runtime.json").read_text(encoding="utf-8")
    )
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "distribution", "source_sha256"}
        or manifest.get("schema_version") != 1
        or manifest.get("distribution") != "tj-work-items"
        or not isinstance(manifest.get("source_sha256"), str)
        or re.fullmatch(r"[a-f0-9]{64}", manifest["source_sha256"]) is None
        or manifest["source_sha256"] != shared_source_digest()
    ):
        raise ItemError(
            "installed shared work-item runtime source differs; "
            "reinstall the selected runtimes"
        )


def require_release(version: str | None, source: str | None) -> None:
    require_shared_runtime()
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
