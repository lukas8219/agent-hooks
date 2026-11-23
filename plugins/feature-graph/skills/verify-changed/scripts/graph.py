#!/usr/bin/env python3
import json
from pathlib import Path
import runpy
import sys


CLIENT = Path(__file__).resolve().parents[2] / "feature-graph/scripts/graph.py"
READ_COMMANDS = {"ping", "whoami", "status", "impact", "read", "uri"}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print("Read-only graph client: " + ", ".join(sorted(READ_COMMANDS)))
        print("impact --changes-json FILE accepts changed_files.py JSON output.")
        return 0
    if args[0] not in READ_COMMANDS:
        print("graph.py: verify-changed permits only read-only commands", file=sys.stderr)
        return 2
    if args[0] == "impact" and "--changes-json" in args:
        if len(args) != 3 or args[1] != "--changes-json":
            print("graph.py: expected impact --changes-json FILE", file=sys.stderr)
            return 2
        try:
            changes = json.loads(Path(args[2]).read_text())
            paths = changes["files"]
            repo = changes["repo"]["name"]
            if not isinstance(paths, list) or not all(isinstance(p, str) and p for p in paths):
                raise ValueError("files must be a list of non-empty paths")
            if not isinstance(repo, str) or not repo:
                raise ValueError("repo.name must be a non-empty string")
        except (OSError, ValueError, KeyError, TypeError) as err:
            print(f"graph.py: invalid changes JSON: {err}", file=sys.stderr)
            return 2
        args = ["impact", "--repo", repo, "--", *paths]
    return runpy.run_path(str(CLIENT))["main"](args)


if __name__ == "__main__":
    sys.exit(main())
