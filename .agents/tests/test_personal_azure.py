from __future__ import annotations

import copy
import io
import json
import re
from collections.abc import Mapping, Sequence
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest
from personal_work_items.azure_api import APIError, Client
from personal_work_items.azure_tracker import Tracker
from personal_work_items.records import ItemError

CONFIG: dict[str, object] = {
    "schema_version": 1,
    "organization": "tj-agents",
    "project": "Personal work items",
    "repository": "tommyboy4050/example",
    "kinds": {
        "feature": "Feature",
        "task": "Task",
        "bug": "Bug",
        "mistake": "Mistake",
        "debt": "Debt",
    },
}


class MemoryJournal:
    def __init__(self) -> None:
        self.receipts: dict[str, dict[str, int | str | None]] = {}

    def read(self, key: str, fingerprint: str) -> dict[str, int | str | None] | None:
        receipt = self.receipts.get(key)
        if receipt is not None and receipt["fingerprint"] != fingerprint:
            raise ItemError(
                "request receipt differs or is invalid; reconcile before submission"
            )
        return receipt

    def reserve(self, key: str, fingerprint: str) -> None:
        if key in self.receipts:
            raise ItemError(
                "request is already reserved; reconcile without another POST"
            )
        self.receipts[key] = {"fingerprint": fingerprint, "resource_id": None}

    def complete(self, key: str, fingerprint: str, resource_id: int) -> None:
        self.receipts[key] = {"fingerprint": fingerprint, "resource_id": resource_id}

    def writer(self) -> Any:
        from contextlib import nullcontext

        return nullcontext()


class FakeAzure:
    def __init__(self) -> None:
        self.items: dict[int, dict[str, object]] = {}
        self.next_id = 1
        self.posts = 0
        self.persist_then_timeout = False
        self.conflict_next = False
        self.unauthorized_wiql = False
        self.drop_created_parent = False
        self.hide_query_results = False

    def request(
        self,
        method: str,
        suffix: str,
        payload: Mapping[str, object] | Sequence[Mapping[str, object]] | None = None,
        content_type: str = "application/json",
    ) -> object:
        if method == "POST" and suffix.startswith("wiql"):
            if self.unauthorized_wiql:
                raise APIError("Azure DevOps POST failed (HTTP 401)", 401)
            assert isinstance(payload, Mapping)
            if self.hide_query_results:
                return {"workItems": []}
            query = payload["query"]
            assert isinstance(query, str)
            return {
                "workItems": [
                    {"id": identifier}
                    for identifier, item in self.items.items()
                    if self._matches(item, query)
                ]
            }
        if method == "POST" and suffix.startswith("workitems/$"):
            assert isinstance(payload, Sequence)
            identifier = self.next_id
            self.next_id += 1
            fields: dict[str, object] = {
                "System.TeamProject": CONFIG["project"],
                "System.WorkItemType": suffix.removeprefix("workitems/$"),
                "System.State": "New",
            }
            item: dict[str, object] = {
                "id": identifier,
                "rev": 1,
                "fields": fields,
                "relations": [],
            }
            self._patch(item, payload)
            if self.drop_created_parent:
                item["relations"] = []
            self.items[identifier] = item
            self.posts += 1
            if self.persist_then_timeout:
                self.persist_then_timeout = False
                raise APIError(
                    "Azure DevOps transport is unavailable; "
                    "a write outcome may be uncertain"
                )
            return copy.deepcopy(item)
        if method == "GET" and suffix.startswith("workitems/"):
            identifier = int(suffix.removeprefix("workitems/").split("?", 1)[0])
            return copy.deepcopy(self.items[identifier])
        if method == "PATCH" and suffix.startswith("workitems/"):
            identifier = int(suffix.removeprefix("workitems/"))
            if self.conflict_next:
                self.conflict_next = False
                raise APIError("Azure DevOps PATCH failed (HTTP 409)", 409)
            assert isinstance(payload, Sequence)
            item = self.items[identifier]
            self._patch(item, payload)
            revision = item["rev"]
            assert isinstance(revision, int)
            item["rev"] = revision + 1
            return copy.deepcopy(item)
        raise AssertionError(f"unexpected Azure request: {method} {suffix}")

    def _matches(self, item: dict[str, object], query: str) -> bool:
        fields = item["fields"]
        assert isinstance(fields, dict)
        checks = {
            "System.TeamProject": fields["System.TeamProject"],
            "Custom.PersonalRepository": fields.get("Custom.PersonalRepository"),
            "Custom.PersonalRequestId": fields.get("Custom.PersonalRequestId"),
            "System.WorkItemType": fields["System.WorkItemType"],
        }
        for field, value in checks.items():
            match = re.search(rf"\[{re.escape(field)}\] = '((?:''|[^'])*)'", query)
            if match is not None and str(value) != match.group(1).replace("''", "'"):
                return False
        return all(
            f"[System.State] <> '{state}'" not in query
            or fields["System.State"] != state
            for state in ("Closed", "Removed")
        )

    def _patch(
        self, item: dict[str, object], patch: Sequence[Mapping[str, object]]
    ) -> None:
        fields = item["fields"]
        relations = item["relations"]
        assert isinstance(fields, dict)
        assert isinstance(relations, list)
        for operation in patch:
            path = operation["path"]
            assert isinstance(path, str)
            if operation["op"] == "test":
                assert path == "/rev"
                if operation["value"] != item["rev"]:
                    raise APIError("Azure DevOps PATCH failed (HTTP 409)", 409)
            elif path.startswith("/fields/"):
                fields[path.removeprefix("/fields/")] = operation["value"]
            elif operation["op"] == "remove" and path.startswith("/relations/"):
                relations.pop(int(path.removeprefix("/relations/")))
            elif operation["op"] == "add" and path == "/relations/-":
                relations.append(operation["value"])
            else:
                raise AssertionError(f"unexpected patch: {operation}")


def record(kind: str) -> dict[str, object]:
    common: dict[str, object] = {
        "kind": kind,
        "title": f"{kind} title",
        "summary": f"{kind} summary",
    }
    specific = {
        "feature": {"outcome": "outcome", "scope": "scope", "acceptance": "acceptance"},
        "task": {"action": "action", "done_when": "done"},
        "bug": {
            "expected": "expected",
            "actual": "actual",
            "evidence": "evidence",
            "impact": "impact",
            "resolution": "resolution",
        },
        "mistake": {
            "evidence": "evidence",
            "cause": "cause",
            "governing_rule": "rule",
            "prevention": "prevention",
            "verification": "verification",
        },
        "debt": {
            "compromise": "compromise",
            "deferred_reason": "reason",
            "impact": "impact",
            "exit_condition": "exit",
        },
    }
    return {**common, **specific[kind]}


def tracker() -> tuple[Tracker, FakeAzure]:
    api = FakeAzure()
    return Tracker(Path(), CONFIG, api, MemoryJournal()), api


def item_id(item: Mapping[str, object]) -> int:
    value = item["id"]
    assert isinstance(value, int)
    return value


@pytest.mark.parametrize("kind", ["feature", "task", "bug", "mistake", "debt"])
def test_create_persists_every_supported_kind(kind: str) -> None:
    value, api = tracker()
    created = value.create(record(kind), f"create-{kind}")
    assert created["kind"] == kind
    assert created["state"] == "New"
    assert created["record"] == record(kind)
    fields = api.items[item_id(created)]["fields"]
    assert isinstance(fields, dict)
    assert fields["Custom.PersonalRepository"] == CONFIG["repository"]


def test_create_deduplicates_a_closed_work_item_without_reopening() -> None:
    value, _ = tracker()
    created = value.create(record("task"), "closed-task")
    value.set_state(str(created["url"]), "closed")
    repeated = value.create(record("task"), "closed-task")
    assert repeated["reconciled"] is True
    assert repeated["state"] == "Closed"


@pytest.mark.parametrize("mutation", ["kind", "hash", "repository"])
def test_read_rejects_wrong_managed_metadata(mutation: str) -> None:
    value, api = tracker()
    created = value.create(record("feature"), "metadata-feature")
    stored = api.items[item_id(created)]
    fields = stored["fields"]
    assert isinstance(fields, dict)
    if mutation == "kind":
        fields["System.WorkItemType"] = "Task"
    elif mutation == "hash":
        metadata = json.loads(str(fields["Custom.PersonalRecord"]))
        metadata["sha256"] = "0" * 64
        fields["Custom.PersonalRecord"] = json.dumps(metadata)
    else:
        fields["Custom.PersonalRepository"] = "tommyboy4050/other"
    with pytest.raises(ItemError):
        value.read(str(created["url"]))


def test_read_rejects_foreign_or_shorthand_url() -> None:
    value, _ = tracker()
    with pytest.raises(ItemError, match="full managed"):
        value.read("1")
    with pytest.raises(ItemError, match="full managed"):
        value.read(
            "https://dev.azure.com/other/Personal%20work%20items/_workitems/edit/1"
        )


def test_task_parent_uses_and_replaces_native_hierarchy_relation() -> None:
    value, api = tracker()
    first = value.create(record("feature"), "feature-first")
    second = value.create(
        {**record("feature"), "title": "other feature"}, "feature-second"
    )
    task = value.create(record("task"), "task-parented", str(first["url"]))
    changed = value.set_parent(str(task["url"]), str(second["url"]))
    relations = api.items[item_id(changed)]["relations"]
    assert relations == [
        {
            "rel": "System.LinkTypes.Hierarchy-Reverse",
            "url": f"https://dev.azure.com/tj-agents/_apis/wit/workItems/{second['id']}",
        }
    ]


def test_update_conflict_requires_reconciliation() -> None:
    value, api = tracker()
    created = value.create(record("task"), "conflict-task")
    api.conflict_next = True
    with pytest.raises(ItemError, match="changed"):
        value.update(str(created["url"]), {**record("task"), "title": "updated title"})


def test_timeout_after_persist_reconciles_without_a_second_post() -> None:
    value, api = tracker()
    api.persist_then_timeout = True
    created = value.create(record("bug"), "timeout-bug")
    assert created["reconciled"] is True
    assert api.posts == 1
    assert len(api.items) == 1


def test_duplicate_request_ids_fail_loudly() -> None:
    value, api = tracker()
    created = value.create(record("debt"), "duplicate-debt")
    duplicate = copy.deepcopy(api.items[item_id(created)])
    duplicate["id"] = 99
    api.items[99] = duplicate
    with pytest.raises(ItemError, match="multiple Azure"):
        value.create(record("debt"), "duplicate-debt")


def test_list_does_not_hide_an_unauthorized_query() -> None:
    value, api = tracker()
    api.unauthorized_wiql = True
    with pytest.raises(APIError, match="401"):
        value.list_items()


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body

    def close(self) -> None:
        return None


def test_client_uses_fixed_personal_endpoint_and_safe_basic_auth() -> None:
    captured: dict[str, object] = {}

    def open_request(request: Any, timeout: float) -> FakeResponse:
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return FakeResponse(b'{"ok":true}')

    client = Client(CONFIG, "token-value", open_request)
    assert client.request("GET", "workitems/1") == {"ok": True}
    assert (
        captured["url"]
        == "https://dev.azure.com/tj-agents/Personal%20work%20items/_apis/wit/workitems/1?api-version=7.1"
    )
    assert captured["authorization"] == "Basic cGVyc29uYWw6dG9rZW4tdmFsdWU="
    assert captured["timeout"] == 15.0


def test_client_error_does_not_expose_server_body_or_token() -> None:
    def fail_request(request: Any, timeout: float) -> FakeResponse:
        raise HTTPError(
            request.full_url,
            401,
            "unauthorized",
            Message(),
            io.BytesIO(b"server-secret"),
        )

    client = Client(CONFIG, "token-value", fail_request)
    with pytest.raises(APIError) as captured:
        client.request("GET", "workitems/1")
    assert "server-secret" not in str(captured.value)
    assert "token-value" not in str(captured.value)


def test_uncertain_create_requires_verified_parent_before_success() -> None:
    value, api = tracker()
    parent = value.create(record("feature"), "parent-for-uncertain-child")
    api.drop_created_parent = True
    api.persist_then_timeout = True
    for _ in range(2):
        with pytest.raises(ItemError, match="parent"):
            value.create(record("task"), "uncertain-child", str(parent["url"]))
    assert api.posts == 2


def test_completed_receipt_requires_parent_when_query_index_lags() -> None:
    value, api = tracker()
    parent = value.create(record("feature"), "parent-for-receipt-child")
    child = value.create(record("task"), "receipt-child", str(parent["url"]))
    api.items[item_id(child)]["relations"] = []
    api.hide_query_results = True
    with pytest.raises(ItemError, match="parent"):
        value.create(record("task"), "receipt-child", str(parent["url"]))
    assert api.posts == 2


@pytest.mark.parametrize("state", ["New", "Active", "Resolved"])
def test_core_reader_accepts_persisted_native_open_bug_state(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    from unittest.mock import Mock

    from personal_work_items import cli, credentials

    value, api = tracker()
    created = value.create(record("bug"), "native-open-bug")
    fields = api.items[item_id(created)]["fields"]
    assert isinstance(fields, dict)
    fields["System.State"] = state
    monkeypatch.setattr(
        cli,
        "load_context",
        Mock(return_value={"primary_root": Path.cwd(), "config": CONFIG}),
    )
    monkeypatch.setattr(
        credentials, "get_pat", Mock(return_value="dummy-personal-token")
    )
    monkeypatch.setattr(cli, "Client", Mock())
    monkeypatch.setattr(cli, "Tracker", Mock(return_value=value))
    result = cli.execute(
        cli._parser().parse_args(["read-problem", "--record", str(created["url"])])
    )
    assert result["record"] == created["url"]
    assert result["state"] == "open"
    assert "bug summary" in result["body"]


@pytest.mark.parametrize("field", ["System.Title", "System.Description"])
@pytest.mark.parametrize("operation", ["read", "list"])
def test_current_facts_reject_human_content_edits(field: str, operation: str) -> None:
    value, api = tracker()
    created = value.create(record("bug"), "human-edited-bug")
    fields = api.items[item_id(created)]["fields"]
    assert isinstance(fields, dict)
    fields[field] = "New facts entered through Azure UI"
    with pytest.raises(ItemError, match="edited outside"):
        if operation == "read":
            value.read(str(created["url"]))
        else:
            value.list_items()


@pytest.mark.parametrize("state", ["Closed", "Removed"])
def test_default_list_excludes_inactive_items_but_preserves_history(state: str) -> None:
    value, api = tracker()
    created = value.create(record("bug"), "inactive-bug")
    fields = api.items[item_id(created)]["fields"]
    assert isinstance(fields, dict)
    fields["System.State"] = state
    assert value.list_items() == []
    history = value.list_items(include_closed=True)
    assert len(history) == 1
    assert history[0]["state"] == state
