import ast
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from personal_work_items import cli, credentials, fingerprint
from tj_work_items.records import KINDS, ItemError, skeleton


def command_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Mock:
    monkeypatch.setattr(
        cli,
        "load_context",
        Mock(
            return_value={
                "primary_root": tmp_path,
                "config": {"organization": "personal-fixture"},
            }
        ),
    )
    credential = Mock(return_value="dummy-personal-token")
    monkeypatch.setattr(credentials, "get_pat", credential)
    monkeypatch.setattr(cli, "Client", Mock())
    monkeypatch.setattr(cli, "RequestJournal", Mock())
    return credential


def test_source_mismatch_rejects_before_context_or_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Mock(side_effect=AssertionError("context must not be read"))
    monkeypatch.setattr(cli, "load_context", context)
    args = cli._parser().parse_args(["--require-source", "0" * 64, "doctor"])
    with pytest.raises(ItemError, match="source differs"):
        cli.execute(args)
    context.assert_not_called()


def test_write_rejects_unretained_stdin_before_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    credential = command_context(monkeypatch, tmp_path)
    args = cli._parser().parse_args(
        ["create", "--input", "-", "--request-id", "retained-input"]
    )
    with pytest.raises(ItemError, match="retained JSON input"):
        cli.execute(args)
    credential.assert_not_called()


@pytest.mark.parametrize(
    "kind,state",
    [("feature", "New"), ("task", "New"), ("bug", "Closed"), ("bug", "Removed")],
)
def test_problem_reader_rejects_ineligible_azure_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str, state: str
) -> None:
    command_context(monkeypatch, tmp_path)
    tracker = Mock()
    tracker.read.return_value = {"kind": kind, "state": state}
    monkeypatch.setattr(cli, "Tracker", Mock(return_value=tracker))
    args = cli._parser().parse_args(
        [
            "read-problem",
            "--record",
            "https://dev.azure.com/personal-fixture/Personal/_workitems/edit/1",
        ]
    )
    with pytest.raises(ItemError, match="current open"):
        cli.execute(args)


def test_problem_reader_emits_core_envelope_with_verified_facts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    command_context(monkeypatch, tmp_path)
    record: dict[str, Any] = dict.fromkeys(skeleton("bug"), "fixture evidence")
    record["kind"] = "bug"
    record["actual"] = "Verified actual behavior from Azure"
    tracker = Mock()
    tracker.read.return_value = {"kind": "bug", "state": "New", "record": record}
    monkeypatch.setattr(cli, "Tracker", Mock(return_value=tracker))
    uri = "https://dev.azure.com/personal-fixture/Personal/_workitems/edit/1"
    result = cli.execute(cli._parser().parse_args(["read-problem", "--record", uri]))
    assert set(result) == {"record", "kind", "state", "body"}
    assert result["record"] == uri
    assert result["kind"] == "bug"
    assert result["state"] == "open"
    assert "Verified actual behavior from Azure" in result["body"]
    tracker.read.assert_called_once_with(uri)


def test_core_reader_shim_accepts_python39_syntax() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "personal/utility/work-item/scripts/read_problem_record.py"
    )
    ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 9))


def test_shared_runtime_mismatch_rejects_before_context_or_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Mock(side_effect=AssertionError("context must not be read"))
    credential = Mock(side_effect=AssertionError("credentials must not be read"))
    monkeypatch.setattr(cli, "load_context", context)
    monkeypatch.setattr(credentials, "get_pat", credential)
    monkeypatch.setattr(fingerprint, "shared_source_digest", lambda: "f" * 64)
    with pytest.raises(ItemError, match="shared work-item runtime source differs"):
        cli.execute(cli._parser().parse_args(["doctor"]))
    context.assert_not_called()
    credential.assert_not_called()


def test_personal_adapter_passes_its_fields_and_existing_receipt_namespace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    command_context(monkeypatch, tmp_path)
    factory = Mock()
    journal = Mock()
    monkeypatch.setattr(cli, "Tracker", factory)
    monkeypatch.setattr(cli, "RequestJournal", journal)
    cli.execute(cli._parser().parse_args(["list"]))
    journal.assert_called_once_with(tmp_path, namespace="personal-work-items")
    assert factory.call_args.kwargs == {
        "fields": {
            "repository": "Custom.PersonalRepository",
            "request": "Custom.PersonalRequestId",
            "record": "Custom.PersonalRecord",
        },
        "lifecycle": {
            kind: {"open": "New", "closed": "Closed", "inactive": ("Closed", "Removed")}
            for kind in KINDS
        },
    }
    assert factory.call_args.args[3] is journal.return_value


def test_shared_journal_reads_existing_personal_receipt(project: Path) -> None:
    from tj_work_items.request_journal import RequestJournal

    key = "personal-fixture/Project/example/personal-project:create:existing"
    fingerprint_value = "a" * 64
    journal = RequestJournal(project, namespace="personal-work-items")
    assert journal.root == project / ".git/personal-work-items/requests"
    journal.root.mkdir(parents=True)
    journal.path(key).write_text(
        '{"fingerprint":"' + fingerprint_value + '","resource_id":null}',
        encoding="utf-8",
    )
    assert journal.read(key, fingerprint_value) == {
        "fingerprint": fingerprint_value,
        "resource_id": None,
    }
    with pytest.raises(ItemError, match="already reserved"):
        journal.reserve(key, fingerprint_value)
