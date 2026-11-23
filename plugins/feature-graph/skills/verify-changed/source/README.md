# AIP compilation provenance

This skill targets [AIP v0.3a3](https://github.com/zach-blumenfeld/aip/tree/v0.3a3),
the version evaluated in [the AIP paper](https://arxiv.org/html/2606.04781v1).
`procedure.schema.json` is the unchanged upstream schema from commit
`2c20a02fe2b6c34eb98476853865a6b07946dc62`, with SHA-256
`3dfd95403f05ed5481dee5ce001e351a2264ac5cec6c411d1685e979cb196c5e`.
`original-SKILL.md` preserves the pre-conversion instructions from agent-hooks
commit `84d6039`. It is provenance, not a second execution entrypoint.

Deterministic Git collection lives in `scripts/changed_files.py`; it emits JSON
and preserves unusual filenames and deleted/renamed paths. The local
`scripts/graph.py` adapter rejects write commands and translates changes JSON
into the existing graph client's arguments. Both scripts intentionally reuse
`../feature-graph/scripts/graph.py` within the same installed plugin. They require
that sibling skill; they are not standalone copies of the Neo4j implementation.
Interface compatibility, runner selection, and interpretation of results remain
judgment steps. `changes-path` is the scratchpad file where the agent captures
collector stdout. Query failures deliberately produce a null graph result plus
an error, allowing the explicit fallback path rather than invented graph data.

| Original content | Compiled location |
|---|---|
| Purpose, activation, read-only behavior | Frontmatter, `purpose`, `scope_and_approval` |
| Credentials and query commands | Neo4j integration, read-only adapter |
| Identity, base selection, committed/worktree/untracked union | `collect-changes`, Git integration |
| Missing remote base and no-change exit | Collector diagnostics, Git integration, terminal no-change branch |
| Deleted paths retained for impact but excluded from tests | Collector output, plan and run steps |
| Impact fields, counterparts, requires, missing mapping | `query-impact`, `plan-verification` |
| Staleness and unrelated history | `plan-verification` |
| Plan format and interface compatibility decisions | `references/verification.md`, loaded by plan step |
| Local-only runners, deduplication, changed specs, missing services | `run-local-tests` |
| `--plan-only` and observed pass/fail | Explicit external input, run step, report step |
| Diff-only fallback, uncertain cross-repo effects | `plan-verification`, default mode |

Intentional changes: replace the shell pipeline with NUL-safe Git collection and
JSON transport; reject graph write subcommands in the adapter; route fallback
plans through the same plan-only gate and local-test/report steps. A separate
ping is unnecessary because impact reports connection failures. AIP validation
checks structure and contracts; it does not enforce the agent's reasoning or
prove the quality of its chosen tests.
