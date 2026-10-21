from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "personal/utility/work-item/runtime/src"),
)

from tj_personal_work_items.records import ItemError
from tj_personal_work_items.request_journal import RequestJournal


def journal(tmp_path: Path, namespace: str = "work-items") -> RequestJournal:
    result = Mock(returncode=0, stdout=str(tmp_path / ".git") + "\n")
    with patch(
        "tj_personal_work_items.request_journal.subprocess.run", return_value=result
    ):
        return RequestJournal(tmp_path, namespace)


def test_namespaces_keep_receipts_isolated_and_preserve_format(tmp_path: Path) -> None:
    personal = journal(tmp_path, "personal-work-items")
    employer = journal(tmp_path, "infonetica-work-items")
    personal.reserve("request", "fingerprint")
    personal.complete("request", "fingerprint", 7)
    assert personal.read("request", "fingerprint") == {
        "fingerprint": "fingerprint",
        "resource_id": 7,
    }
    assert employer.read("request", "fingerprint") is None
    assert personal.path("request").parent.name == "requests"
    assert personal.path("request").parent.parent.name == "personal-work-items"


@pytest.mark.parametrize("namespace", ["", "../personal", "personal/work", "UPPER"])
def test_namespace_must_be_one_safe_path_segment(
    tmp_path: Path, namespace: str
) -> None:
    with pytest.raises(ItemError, match="namespace"):
        journal(tmp_path, namespace)


def test_reservation_blocks_second_writer_and_preserves_pending_receipt(
    tmp_path: Path,
) -> None:
    value = journal(tmp_path)
    value.reserve("request", "fingerprint")
    assert value.read("request", "fingerprint") == {
        "fingerprint": "fingerprint",
        "resource_id": None,
    }
    with pytest.raises(ItemError, match="already reserved"):
        value.reserve("request", "fingerprint")
