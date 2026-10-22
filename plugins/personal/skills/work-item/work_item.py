import argparse
import json
import sys

from runtime_bootstrap import bootstrap

bootstrap()

from tj_personal_work_items.records import KINDS, ItemError, schema_for, skeleton, read_input, render, validate


def parser():
    result = argparse.ArgumentParser(description="Deterministic, explicitly selected work-item tools")
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("schema", "template"):
        command = commands.add_parser(name)
        command.add_argument("--kind", choices=KINDS, required=True)
    for name in ("validate", "preview"):
        command = commands.add_parser(name)
        command.add_argument("--input", required=True, help="UTF-8 JSON path, or - for stdin")
    provider = commands.add_parser("provider")
    provider.add_argument("--root", required=True)
    from github_tracker import add_commands
    add_commands(commands, ("create", "read", "list", "state"))
    return result


def run(arguments):
    if arguments.command == "provider":
        from github_tracker import selection
        return selection(arguments.root)
    if arguments.command == "schema":
        return schema_for(arguments.kind)
    if arguments.command == "template":
        return skeleton(arguments.kind)
    if arguments.command not in ("validate", "preview"):
        from github_tracker import execute
        return execute(arguments)
    item = read_input(arguments.input)
    if arguments.command == "validate":
        return {"valid": True, "kind": item["kind"]}
    return {"title": item["title"], "body": render(item)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        output = run(parser().parse_args())
        print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (ItemError, OSError, UnicodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
