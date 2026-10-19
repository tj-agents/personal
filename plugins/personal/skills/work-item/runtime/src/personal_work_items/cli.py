import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Any

from tj_work_items.azure_api import APIError, Client
from tj_work_items.azure_tracker import Tracker
from tj_work_items.records import (
    KINDS,
    ItemError,
    read_input,
    render,
    skeleton,
    validate,
)
from tj_work_items.request_journal import RequestJournal

from . import __version__, credentials
from .configuration import configure
from .context import ContextError, load_context
from .fingerprint import require_release, source_digest
from .host_scope import isolate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Personal Azure Boards work items")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--require-version")
    parser.add_argument("--require-source")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    schema = commands.add_parser("schema")
    schema.add_argument("kind", choices=KINDS)
    check = commands.add_parser("validate")
    check.add_argument("--input", default="-")
    create = commands.add_parser("create")
    create.add_argument("--input", required=True)
    create.add_argument("--request-id", required=True)
    create.add_argument("--parent")
    listing = commands.add_parser("list")
    listing.add_argument("--kind", choices=KINDS)
    listing.add_argument("--include-closed", action="store_true")
    for name in ("read", "read-problem", "update", "state", "parent"):
        command = commands.add_parser(name)
        command.add_argument("--record", required=True)
        if name == "update":
            command.add_argument("--input", required=True)
        if name == "state":
            command.add_argument("value", choices=("open", "closed"))
        if name == "parent":
            command.add_argument("--parent", required=True)
    credential = commands.add_parser("credentials")
    credential.add_argument("action", choices=("store", "delete"))
    commands.add_parser("doctor")
    host = commands.add_parser("isolate")
    host.add_argument("--repository", required=True)
    host.add_argument(
        "--mode", choices=("preview", "write", "check"), default="preview"
    )
    configure = commands.add_parser("configure")
    configure.add_argument("--organization", required=True)
    configure.add_argument("--project", required=True)
    configure.add_argument("--repository", required=True)
    configure.add_argument(
        "--mode", choices=("preview", "write", "check"), default="preview"
    )
    return parser


def execute(args: argparse.Namespace) -> Any:
    require_release(args.require_version, args.require_source)
    if args.command == "schema":
        return skeleton(args.kind)
    if args.command == "validate":
        return read_input(args.input)
    if args.command == "configure":
        return configure(
            args.root, args.organization, args.project, args.repository, args.mode
        )
    if args.command == "isolate":
        return isolate(
            args.root, args.repository, Path.home() / ".claude.json", args.mode
        )
    selected = load_context(args.root)
    config = selected["config"]
    organization = str(config["organization"])
    if args.command == "doctor":
        return {"runtime": __version__, "source": source_digest(), "config": config}
    if args.command == "credentials":
        if args.action == "delete":
            credentials.delete_pat(organization)
        else:
            token = getpass.getpass(
                "Personal Azure DevOps PAT (stored in the OS credential store): "
            )
            credentials.store_pat(organization, token)
        return {"organization": organization, "credential": args.action}
    if args.command in ("create", "update") and args.input == "-":
        raise ItemError("writes require a retained JSON input file")
    token = credentials.get_pat(organization)
    tracker = Tracker(
        selected["primary_root"],
        config,
        Client(config, token),
        RequestJournal(selected["primary_root"], namespace="personal-work-items"),
        fields={
            "repository": "Custom.PersonalRepository",
            "request": "Custom.PersonalRequestId",
            "record": "Custom.PersonalRecord",
        },
        lifecycle={
            kind: {
                "open": "New",
                "closed": "Closed",
                "inactive": ("Closed", "Removed"),
            }
            for kind in KINDS
        },
    )
    if args.command == "create":
        return tracker.create(read_input(args.input), args.request_id, args.parent)
    if args.command == "list":
        return tracker.list_items(args.kind, args.include_closed)
    if args.command == "read":
        return tracker.read(args.record)
    if args.command == "update":
        return tracker.update(args.record, read_input(args.input))
    if args.command == "state":
        return tracker.set_state(args.record, args.value)
    if args.command == "parent":
        return tracker.set_parent(args.record, args.parent)
    if args.command == "read-problem":
        current = tracker.read(args.record)
        if current["kind"] not in ("bug", "mistake", "debt") or current[
            "state"
        ] not in ("New", "Active", "Resolved"):
            raise ItemError("record must be a current open personal problem")
        return {
            "record": args.record,
            "kind": current["kind"],
            "state": "open",
            "body": render(validate(current["record"])),
        }
    raise ItemError("unsupported personal work-item command")


def main() -> int:
    args = _parser().parse_args()
    try:
        result = execute(args)
    except (
        ContextError,
        credentials.CredentialError,
        ItemError,
        APIError,
        OSError,
        ValueError,
    ):
        print(
            "Personal work-item operation failed; check repository "
            "selection, credentials and record state with doctor before retrying.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
