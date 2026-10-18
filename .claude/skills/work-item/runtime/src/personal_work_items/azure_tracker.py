from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Protocol, TypedDict
from urllib.parse import quote, urlsplit

from .azure_api import APIError
from .records import ItemError, render, validate
from .request_journal import RequestJournal

_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_METADATA_FIELDS = {"schema_version", "request_id", "record", "sha256"}


class AzureClient(Protocol):
    def request(
        self,
        method: str,
        suffix: str,
        payload: Mapping[str, object] | Sequence[Mapping[str, object]] | None = None,
        content_type: str = "application/json",
    ) -> object: ...


class Journal(Protocol):
    def read(
        self, key: str, fingerprint: str
    ) -> dict[str, int | str | None] | None: ...

    def reserve(self, key: str, fingerprint: str) -> None: ...

    def complete(self, key: str, fingerprint: str, resource_id: int) -> None: ...

    def writer(self) -> AbstractContextManager[None]: ...


class WorkItemResponse(TypedDict):
    id: int
    raw: dict[str, object]


class Metadata(TypedDict):
    request_id: str
    record: dict[str, object]
    sha256: str


class ManagedItem(TypedDict):
    url: str
    id: int
    kind: str
    state: str
    record: dict[str, object]
    revision: int


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _request_id(value: str) -> str:
    if not _REQUEST_ID.fullmatch(value):
        raise ItemError(
            "request-id must contain 1-128 letters, digits, dots, colons, dashes, "
            "or underscores"
        )
    return value


def _positive_id(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ItemError("Azure DevOps returned an invalid work-item identity")
    return value


def _mapping(value: object, message: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ItemError(message)
    return value


def _html_from_markdown(markdown: str) -> str:
    blocks: list[str] = []
    paragraph: list[str] = []
    code: list[str] | None = None
    for line in markdown.splitlines():
        if line.startswith("```"):
            if code is None:
                if paragraph:
                    blocks.append(
                        "<p>"
                        + "<br/>".join(html.escape(value) for value in paragraph)
                        + "</p>"
                    )
                    paragraph = []
                code = []
            else:
                blocks.append("<pre>" + html.escape("\n".join(code)) + "</pre>")
                code = None
            continue
        if code is not None:
            code.append(line)
        elif not line:
            if paragraph:
                blocks.append(
                    "<p>"
                    + "<br/>".join(html.escape(value) for value in paragraph)
                    + "</p>"
                )
                paragraph = []
        else:
            paragraph.append(line)
    if code is not None:
        raise ItemError("rendered work-item content has an unclosed code block")
    if paragraph:
        blocks.append(
            "<p>" + "<br/>".join(html.escape(value) for value in paragraph) + "</p>"
        )
    return "".join(blocks)


def _same_html(actual: str, expected: str) -> bool:
    return actual.replace("\r\n", "\n").replace("<br>", "<br/>") == expected.replace(
        "\r\n", "\n"
    ).replace("<br>", "<br/>")


class Tracker:
    def __init__(
        self,
        root: Path,
        context_config: Mapping[str, object],
        client: AzureClient | None = None,
        journal: Journal | None = None,
    ) -> None:
        self.root = Path(root)
        self.config = dict(context_config)
        self.organization = self._config_text("organization")
        self.project = self._config_text("project")
        self.repository = self._config_text("repository").lower()
        kinds = self.config.get("kinds")
        if not isinstance(kinds, dict) or set(kinds) != {
            "feature",
            "task",
            "bug",
            "mistake",
            "debt",
        }:
            raise ItemError("personal Azure work-item type mapping is invalid")
        if any(
            not isinstance(key, str) or not isinstance(value, str) or not value
            for key, value in kinds.items()
        ):
            raise ItemError("personal Azure work-item type mapping is invalid")
        if len(set(kinds.values())) != len(kinds):
            raise ItemError("personal Azure work-item type mapping must be distinct")
        self.kinds: dict[str, str] = {}
        for key, value in kinds.items():
            assert isinstance(key, str)
            assert isinstance(value, str)
            self.kinds[key] = value
        if client is None:
            raise ItemError(
                "personal Azure work-item operations require an authenticated "
                "Azure client"
            )
        self.client = client
        self.journal = journal if journal is not None else RequestJournal(self.root)

    def create(
        self, item: Mapping[str, object], request_id: str, parent: str | None = None
    ) -> dict[str, object]:
        record = self._validated(item)
        request = _request_id(request_id)
        parent_id = self._creation_parent(record, parent)
        fingerprint = _hash(
            {
                "record": record,
                "parent_id": parent_id,
                "organization": self.organization,
                "project": self.project,
                "repository": self.repository,
            }
        )
        key = f"{self.organization}/{self.project}/{self.repository}:create:{request}"
        writer = self.journal.writer() if self.journal is not None else nullcontext()
        with writer:
            receipt = (
                self.journal.read(key, fingerprint)
                if self.journal is not None
                else None
            )
            found = self._find_request(request, record)
            if found is not None:
                if parent_id is not None:
                    self._require_parent(found["raw"], parent_id)
                if self.journal is not None:
                    self.journal.complete(key, fingerprint, _positive_id(found["id"]))
                return {**self._managed(found["raw"]), "reconciled": True}
            if receipt is not None and receipt["resource_id"] is not None:
                recovered = self._read_id(_positive_id(receipt["resource_id"]))
                self._same_create(recovered, request, record)
                return {**self._managed(recovered["raw"]), "reconciled": True}
            if receipt is not None:
                raise ItemError(
                    "request outcome remains uncertain; reconcile without another POST"
                )
            if self.journal is not None:
                self.journal.reserve(key, fingerprint)
            patch = self._create_patch(record, request, parent_id)
            try:
                response = self.client.request(
                    "POST",
                    f"workitems/${self.kinds[self._kind(record)]}",
                    patch,
                    "application/json-patch+json",
                )
                response_id = _positive_id(
                    _mapping(
                        response, "Azure DevOps returned an invalid create response"
                    ).get("id")
                )
                created = self._read_id(response_id)
                self._same_create(created, request, record)
                if parent_id is not None:
                    self._require_parent(created["raw"], parent_id)
            except APIError as error:
                found = self._find_request(request, record)
                if found is not None:
                    if self.journal is not None:
                        self.journal.complete(
                            key, fingerprint, _positive_id(found["id"])
                        )
                    return {**self._managed(found["raw"]), "reconciled": True}
                raise ItemError(
                    "create outcome uncertain or rejected; retain request-id and "
                    "reconcile before retrying"
                ) from error
            if self.journal is not None:
                self.journal.complete(key, fingerprint, _positive_id(created["id"]))
            return {**self._managed(created["raw"]), "reconciled": False}

    def read(self, url: str) -> ManagedItem:
        return self._managed(self._read_id(self._url_id(url))["raw"])

    def list_items(
        self, kind: str | None = None, include_closed: bool = False
    ) -> list[ManagedItem]:
        if kind is not None and kind not in self.kinds:
            raise ItemError("kind must name a supported personal work-item type")
        clauses = [
            f"[System.TeamProject] = {self._wiql_literal(self.project)}",
            f"[Custom.PersonalRepository] = {self._wiql_literal(self.repository)}",
        ]
        if kind is not None:
            clauses.append(
                f"[System.WorkItemType] = {self._wiql_literal(self.kinds[kind])}"
            )
        if not include_closed:
            clauses.append("[System.State] <> 'Closed'")
        query = "SELECT [System.Id] FROM WorkItems WHERE " + " AND ".join(clauses)
        response = _mapping(
            self.client.request("POST", "wiql?$top=1000", {"query": query}),
            "Azure DevOps returned an invalid WIQL response",
        )
        work_items = response.get("workItems")
        if not isinstance(work_items, list):
            raise ItemError("Azure DevOps returned an invalid WIQL response")
        result: list[ManagedItem] = []
        for entry in work_items:
            identifier = _positive_id(
                _mapping(entry, "Azure DevOps returned an invalid WIQL identity").get(
                    "id"
                )
            )
            managed = self._managed(self._read_id(identifier)["raw"])
            if kind is not None and managed["kind"] != kind:
                raise ItemError(
                    "Azure DevOps WIQL returned a work item of the wrong kind"
                )
            if not include_closed and managed["state"] == "Closed":
                raise ItemError("Azure DevOps WIQL returned a closed work item")
            result.append(managed)
        return result

    def update(self, url: str, item: Mapping[str, object]) -> ManagedItem:
        current = self._read_id(self._url_id(url))
        managed = self._managed(current["raw"])
        record = self._validated(item)
        if self._kind(record) != managed["kind"]:
            raise ItemError("update cannot change the work-item kind")
        self._require_unedited(current["raw"])
        metadata = self._metadata(current["raw"])
        patch: list[dict[str, object]] = [
            {"op": "test", "path": "/rev", "value": managed["revision"]},
            {"op": "replace", "path": "/fields/System.Title", "value": record["title"]},
            {
                "op": "replace",
                "path": "/fields/System.Description",
                "value": self._description(record),
            },
            {
                "op": "replace",
                "path": "/fields/Custom.PersonalRecord",
                "value": self._metadata_text(record, metadata["request_id"]),
            },
        ]
        try:
            response = self.client.request(
                "PATCH",
                f"workitems/{managed['id']}",
                patch,
                "application/json-patch+json",
            )
            updated = self._read_id(
                _positive_id(
                    _mapping(
                        response, "Azure DevOps returned an invalid update response"
                    ).get("id")
                )
            )
        except APIError as error:
            if error.status == 409:
                raise ItemError(
                    "work item changed; read and reconcile current content before "
                    "updating"
                ) from error
            raise ItemError(
                "update outcome uncertain; read the work item before retrying"
            ) from error
        updated_managed = self._managed(updated["raw"])
        if updated_managed["record"] != record:
            raise ItemError("Azure DevOps did not preserve the updated work-item facts")
        return updated_managed

    def set_state(self, url: str, state: str) -> ManagedItem:
        if state not in {"open", "closed"}:
            raise ItemError("state action must be open or closed")
        current = self._read_id(self._url_id(url))
        managed = self._managed(current["raw"])
        target = "New" if state == "open" else "Closed"
        if managed["state"] == target:
            return managed
        patch: list[dict[str, object]] = [
            {"op": "test", "path": "/rev", "value": managed["revision"]},
            {"op": "replace", "path": "/fields/System.State", "value": target},
        ]
        try:
            response = self.client.request(
                "PATCH",
                f"workitems/{managed['id']}",
                patch,
                "application/json-patch+json",
            )
            updated = self._read_id(
                _positive_id(
                    _mapping(
                        response, "Azure DevOps returned an invalid state response"
                    ).get("id")
                )
            )
        except APIError as error:
            if error.status == 409:
                raise ItemError(
                    "work item changed; read and reconcile current content before "
                    "changing state"
                ) from error
            raise ItemError(
                "state change outcome uncertain; read the work item before retrying"
            ) from error
        result = self._managed(updated["raw"])
        if result["state"] != target:
            raise ItemError("Azure DevOps did not preserve the requested state")
        return result

    def set_parent(self, url: str, parent_url: str) -> ManagedItem:
        child = self._read_id(self._url_id(url))
        child_managed = self._managed(child["raw"])
        if child_managed["kind"] != "task":
            raise ItemError("only task work items can have a Feature parent")
        parent_id = self._url_id(parent_url)
        if parent_id == child_managed["id"]:
            raise ItemError("a work item cannot parent itself")
        parent = self._read_id(parent_id)
        if self._managed(parent["raw"])["kind"] != "feature":
            raise ItemError("a task parent must be a Feature work item")
        relations = self._relations(child["raw"])
        existing = self._parent_relation_indices(relations)
        if existing and any(
            self._relation_parent_id(relations[index]) != parent_id
            for index in existing
        ):
            for index in existing:
                existing_parent = self._read_id(
                    self._relation_parent_id(relations[index])
                )
                if self._managed(existing_parent["raw"])["kind"] != "feature":
                    raise ItemError(
                        "task has a non-Feature parent; reconcile before replacing it"
                    )
        if existing and all(
            self._relation_parent_id(relations[index]) == parent_id
            for index in existing
        ):
            if len(existing) != 1:
                raise ItemError(
                    "task has duplicate parent relations; reconcile before replacing it"
                )
            return child_managed
        patch: list[dict[str, object]] = [
            {"op": "test", "path": "/rev", "value": child_managed["revision"]}
        ]
        for index in reversed(existing):
            patch.append({"op": "remove", "path": f"/relations/{index}"})
        patch.append(
            {
                "op": "add",
                "path": "/relations/-",
                "value": self._parent_relation(parent_id),
            }
        )
        try:
            response = self.client.request(
                "PATCH",
                f"workitems/{child_managed['id']}",
                patch,
                "application/json-patch+json",
            )
            updated = self._read_id(
                _positive_id(
                    _mapping(
                        response, "Azure DevOps returned an invalid parent response"
                    ).get("id")
                )
            )
        except APIError as error:
            if error.status == 409:
                raise ItemError(
                    "work item changed; read and reconcile current parent before "
                    "replacing it"
                ) from error
            raise ItemError(
                "parent change outcome uncertain; read the work item before retrying"
            ) from error
        self._require_parent(updated["raw"], parent_id)
        return self._managed(updated["raw"])

    def _config_text(self, name: str) -> str:
        value = self.config.get(name)
        if not isinstance(value, str) or not value:
            raise ItemError("personal Azure work-item configuration is invalid")
        return value

    def _validated(self, item: Mapping[str, object]) -> dict[str, object]:
        try:
            value = validate(dict(item))
        except (TypeError, ValueError) as error:
            raise ItemError(str(error)) from error
        result = _mapping(value, "work-item validation returned an invalid record")
        kind = result.get("kind")
        if not isinstance(kind, str) or kind not in self.kinds:
            raise ItemError(
                "work-item kind is not configured for personal Azure Boards"
            )
        return result

    def _kind(self, record: Mapping[str, object]) -> str:
        kind = record.get("kind")
        if not isinstance(kind, str) or kind not in self.kinds:
            raise ItemError(
                "work-item kind is not configured for personal Azure Boards"
            )
        return kind

    def _description(self, record: Mapping[str, object]) -> str:
        rendered = render(dict(record))
        if not isinstance(rendered, str) or not rendered:
            raise ItemError("work-item renderer returned invalid content")
        return _html_from_markdown(rendered)

    def _metadata_text(self, record: Mapping[str, object], request_id: str) -> str:
        facts = self._validated(record)
        return _json(
            {
                "schema_version": 1,
                "request_id": request_id,
                "record": facts,
                "sha256": _hash(facts),
            }
        )

    def _create_patch(
        self, record: Mapping[str, object], request_id: str, parent_id: int | None
    ) -> list[dict[str, object]]:
        patch: list[dict[str, object]] = [
            {"op": "add", "path": "/fields/System.Title", "value": record["title"]},
            {
                "op": "add",
                "path": "/fields/System.Description",
                "value": self._description(record),
            },
            {
                "op": "add",
                "path": "/fields/Custom.PersonalRequestId",
                "value": request_id,
            },
            {
                "op": "add",
                "path": "/fields/Custom.PersonalRepository",
                "value": self.repository,
            },
            {
                "op": "add",
                "path": "/fields/Custom.PersonalRecord",
                "value": self._metadata_text(record, request_id),
            },
        ]
        if parent_id is not None:
            patch.append(
                {
                    "op": "add",
                    "path": "/relations/-",
                    "value": self._parent_relation(parent_id),
                }
            )
        return patch

    def _read_id(self, work_item_id: int) -> WorkItemResponse:
        raw = _mapping(
            self.client.request("GET", f"workitems/{work_item_id}?$expand=relations"),
            "Azure DevOps returned an invalid work-item response",
        )
        if _positive_id(raw.get("id")) != work_item_id:
            raise ItemError("Azure DevOps returned a work item with the wrong identity")
        self._managed(raw)
        return {"id": work_item_id, "raw": raw}

    def _managed(self, raw: Mapping[str, object]) -> ManagedItem:
        fields = _mapping(
            raw.get("fields"), "Azure DevOps work item has invalid fields"
        )
        if fields.get("System.TeamProject") != self.project:
            raise ItemError("work item belongs to a different Azure DevOps project")
        if fields.get("Custom.PersonalRepository") != self.repository:
            raise ItemError("work item belongs to a different personal repository")
        work_item_type = fields.get("System.WorkItemType")
        if not isinstance(work_item_type, str):
            raise ItemError("Azure DevOps work item has no configured type")
        kinds = [kind for kind, value in self.kinds.items() if value == work_item_type]
        if len(kinds) != 1:
            raise ItemError("Azure DevOps work item has an unconfigured type")
        metadata = self._metadata(raw)
        record = metadata["record"]
        if record.get("kind") != kinds[0]:
            raise ItemError("Azure DevOps work-item metadata does not match its type")
        work_item_id = _positive_id(raw.get("id"))
        revision = _positive_id(raw.get("rev"))
        title = fields.get("System.Title")
        description = fields.get("System.Description")
        state = fields.get("System.State")
        if (
            not isinstance(title, str)
            or not isinstance(description, str)
            or not isinstance(state, str)
            or not state
        ):
            raise ItemError("Azure DevOps work item has invalid managed fields")
        return {
            "url": self._uri(work_item_id),
            "id": work_item_id,
            "kind": kinds[0],
            "state": state,
            "record": record,
            "revision": revision,
        }

    def _metadata(self, raw: Mapping[str, object]) -> Metadata:
        fields = _mapping(
            raw.get("fields"), "Azure DevOps work item has invalid fields"
        )
        encoded = fields.get("Custom.PersonalRecord")
        request_id = fields.get("Custom.PersonalRequestId")
        if not isinstance(encoded, str) or not isinstance(request_id, str):
            raise ItemError("work item is not managed by personal:work-item")
        try:
            metadata = json.loads(encoded)
        except json.JSONDecodeError as error:
            raise ItemError("work-item metadata is invalid") from error
        value = _mapping(metadata, "work-item metadata is invalid")
        if set(value) != _METADATA_FIELDS or value.get("schema_version") != 1:
            raise ItemError("work-item metadata is invalid")
        metadata_request = value.get("request_id")
        record = value.get("record")
        digest = value.get("sha256")
        if not isinstance(metadata_request, str) or metadata_request != request_id:
            raise ItemError("work-item metadata request identity is invalid")
        _request_id(metadata_request)
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ItemError("work-item metadata hash is invalid")
        record_value = self._validated(
            _mapping(record, "work-item metadata record is invalid")
        )
        if _hash(record_value) != digest:
            raise ItemError("work-item metadata hash does not match its record")
        return {
            "request_id": metadata_request,
            "record": record_value,
            "sha256": digest,
        }

    def _find_request(
        self, request_id: str, record: Mapping[str, object]
    ) -> WorkItemResponse | None:
        query = "SELECT [System.Id] FROM WorkItems WHERE " + " AND ".join(
            [
                f"[System.TeamProject] = {self._wiql_literal(self.project)}",
                f"[Custom.PersonalRepository] = {self._wiql_literal(self.repository)}",
                f"[Custom.PersonalRequestId] = {self._wiql_literal(request_id)}",
            ]
        )
        response = _mapping(
            self.client.request("POST", "wiql?$top=2", {"query": query}),
            "Azure DevOps returned an invalid WIQL response",
        )
        entries = response.get("workItems")
        if not isinstance(entries, list):
            raise ItemError("Azure DevOps returned an invalid WIQL response")
        if len(entries) > 1:
            raise ItemError(
                "request-id has multiple Azure work items; reconcile their ownership "
                "before continuing"
            )
        if not entries:
            return None
        found = self._read_id(
            _positive_id(
                _mapping(
                    entries[0], "Azure DevOps returned an invalid WIQL identity"
                ).get("id")
            )
        )
        self._same_create(found, request_id, record)
        return found

    def _same_create(
        self, found: Mapping[str, object], request_id: str, record: Mapping[str, object]
    ) -> None:
        metadata = self._metadata(
            _mapping(
                found.get("raw"), "Azure DevOps returned an invalid work-item response"
            )
        )
        if metadata["request_id"] != request_id or metadata["record"] != record:
            raise ItemError("request-id already exists with different work-item facts")

    def _creation_parent(
        self, record: Mapping[str, object], parent: str | None
    ) -> int | None:
        if parent is None:
            return None
        if record.get("kind") != "task":
            raise ItemError("only task work items can have a Feature parent")
        parent_id = self._url_id(parent)
        parent_item = self._read_id(parent_id)
        if self._managed(parent_item["raw"])["kind"] != "feature":
            raise ItemError("a task parent must be a Feature work item")
        return parent_id

    def _require_parent(self, raw: Mapping[str, object], parent_id: int) -> None:
        matches = [
            self._relation_parent_id(value)
            for value in self._relations(raw)
            if self._is_parent_relation(value)
        ]
        if matches != [parent_id]:
            raise ItemError(
                "Azure DevOps did not preserve the requested Feature parent"
            )

    def _require_unedited(self, raw: Mapping[str, object]) -> None:
        fields = _mapping(
            raw.get("fields"), "Azure DevOps work item has invalid fields"
        )
        record = self._metadata(raw)["record"]
        title = fields.get("System.Title")
        description = fields.get("System.Description")
        if (
            title != record["title"]
            or not isinstance(description, str)
            or not _same_html(description, self._description(record))
        ):
            raise ItemError(
                "work item was edited outside personal:work-item; reconcile before "
                "overwriting it"
            )

    def _relations(self, raw: Mapping[str, object]) -> list[dict[str, object]]:
        relations = raw.get("relations", [])
        if not isinstance(relations, list) or any(
            not isinstance(value, dict) for value in relations
        ):
            raise ItemError("Azure DevOps work item has invalid relations")
        return relations

    def _parent_relation_indices(
        self, relations: Sequence[Mapping[str, object]]
    ) -> list[int]:
        return [
            index
            for index, relation in enumerate(relations)
            if self._is_parent_relation(relation)
        ]

    def _is_parent_relation(self, relation: Mapping[str, object]) -> bool:
        return relation.get("rel") == "System.LinkTypes.Hierarchy-Reverse"

    def _relation_parent_id(self, relation: Mapping[str, object]) -> int:
        url = relation.get("url")
        if not isinstance(url, str):
            raise ItemError("Azure DevOps parent relation is invalid")
        match = re.fullmatch(
            rf"https://dev\.azure\.com/{re.escape(self.organization)}/_apis/wit/workItems/([1-9][0-9]*)",
            url,
        )
        if match is None:
            raise ItemError(
                "Azure DevOps parent relation targets a different organization"
            )
        return int(match.group(1))

    def _parent_relation(self, parent_id: int) -> dict[str, object]:
        return {
            "rel": "System.LinkTypes.Hierarchy-Reverse",
            "url": f"https://dev.azure.com/{self.organization}/_apis/wit/workItems/{parent_id}",
        }

    def _url_id(self, url: str) -> int:
        if not isinstance(url, str):
            raise ItemError("work item must be a full managed Azure DevOps URL")
        parsed = urlsplit(url)
        expected_prefix = (
            f"/{self.organization}/{quote(self.project, safe='')}/_workitems/edit/"
        )
        if (
            parsed.scheme != "https"
            or parsed.netloc != "dev.azure.com"
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith(expected_prefix)
        ):
            raise ItemError("work item must be a full managed Azure DevOps URL")
        identifier = parsed.path.removeprefix(expected_prefix)
        if not re.fullmatch(r"[1-9][0-9]*", identifier):
            raise ItemError("work item must be a full managed Azure DevOps URL")
        return int(identifier)

    def _uri(self, work_item_id: int) -> str:
        return (
            f"https://dev.azure.com/{self.organization}/"
            f"{quote(self.project, safe='')}/_workitems/edit/{work_item_id}"
        )

    def _wiql_literal(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"
