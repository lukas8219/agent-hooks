#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import runpy
import subprocess
import sys


CLIENT = Path(__file__).resolve().parents[2] / "feature-graph/scripts/graph.py"


def git(*args, cwd=None):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def collect(base_ref=None):
    repo = runpy.run_path(str(CLIENT))["whoami"]()
    if not repo["root"] or not repo["sha"]:
        raise ValueError("run in a Git repository with a HEAD commit")
    selected = base_ref or f"origin/{repo['default_branch']}"
    try:
        base_sha = git("rev-parse", "--verify", "--end-of-options", f"{selected}^{{commit}}", cwd=repo["root"]).strip()
    except ValueError as err:
        if base_ref is None:
            raise ValueError(f"{selected} is missing; fetch origin {repo['default_branch']} and retry") from err
        raise
    merge_base = git("merge-base", base_sha, "HEAD", cwd=repo["root"]).strip()
    files = set()
    for args in (
        ("diff", "--name-only", "--no-renames", "-z", f"{merge_base}...HEAD", "--"),
        ("diff", "--name-only", "--no-renames", "-z", "HEAD", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        files.update(path for path in git(*args, cwd=repo["root"]).split("\0") if path)
    root = Path(repo["root"])
    return {
        "repo": repo,
        "base_ref": selected,
        "base_sha": base_sha,
        "merge_base": merge_base,
        "files": sorted(files),
        "deleted_files": sorted(p for p in files if not (root / p).exists()),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collect committed, staged, unstaged, and untracked changes as JSON")
    parser.add_argument("--base-ref")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(collect(args.base_ref), indent=2))
    except (OSError, ValueError) as err:
        print(f"changed_files.py: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
