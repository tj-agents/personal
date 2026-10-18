import argparse
import ast
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read one current personal Azure problem"
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--record", required=True)
    args = parser.parse_args()
    package = Path(__file__).resolve().parents[1] / "runtime/src/personal_work_items"
    try:
        tree = ast.parse((package / "__init__.py").read_text(encoding="utf-8"))
        versions = [
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__version__"
                for target in node.targets
            )
        ]
        if len(versions) != 1 or not isinstance(versions[0], str):
            raise ValueError("missing runtime version")
        digest = hashlib.sha256()
        for path in sorted(package.rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json"):
                digest.update(
                    path.relative_to(package).as_posix().encode("utf-8") + b"\0"
                )
                digest.update(path.read_bytes() + b"\0")
        executable = shutil.which("personal-work-item")
        if executable is None:
            raise ValueError(
                "install the selected personal runtime before reading records"
            )
        result = subprocess.run(
            [
                executable,
                "--require-version",
                versions[0],
                "--require-source",
                digest.hexdigest(),
                "--root",
                args.root,
                "read-problem",
                "--record",
                args.record,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=13,
            check=False,
        )
        if result.returncode:
            raise ValueError("personal record could not be verified")
    except (OSError, ValueError, subprocess.SubprocessError):
        print(
            "Personal problem reader failed; verify the selected runtime "
            "installation and personal record.",
            file=sys.stderr,
        )
        return 1
    print(result.stdout, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
