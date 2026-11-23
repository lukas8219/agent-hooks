# AIP compilation provenance

This skill targets [AIP v0.3a3](https://github.com/zach-blumenfeld/aip/tree/v0.3a3),
the version evaluated in [the AIP paper](https://arxiv.org/html/2606.04781v1).
`procedure.schema.json` is the unchanged upstream schema from commit
`2c20a02fe2b6c34eb98476853865a6b07946dc62`, with SHA-256
`3dfd95403f05ed5481dee5ce001e351a2264ac5cec6c411d1685e979cb196c5e`.
`original-SKILL.md` preserves the pre-conversion instructions from agent-hooks
commit `84d6039`. It is provenance, not a second execution entrypoint.

The existing Neo4j feature model and client remain unchanged. AIP describes the
agent's procedure, not the repository graph stored in Neo4j. Graph commands are
script-backed; feature discovery, evidence assessment, and approval remain
judgment steps. Each command's invocation is in its step description, and its
JSON result supplies the declared output. Stop on script failure; do not fabricate
an output to satisfy a downstream dependency.

| Original content | Compiled location |
|---|---|
| Purpose and cross-repository ownership | `purpose`, full mode, integration |
| Setup and environment requirements | Neo4j integration, script paths |
| Static-only scope, secrets, source protection, allowed writes | `scope_and_approval`, anti-patterns |
| Preflight identity and status | `identify-repository`, `inspect-graph` |
| Existing-map status-only invocation | Terminal branch of `select-scope` |
| Discovery and optional area subagents | `discover-map`, unchanged discovery reference |
| File roles, confidence, checks, normalized interfaces | `discover-map`, unchanged schema/discovery references |
| User confirmation and declared dependencies | `confirm-mapping` |
| Full/partial payload, scratchpad, validation, upsert | `prepare-payload` through `write-graph` |
| Counts, cross-repo links, dangling consumes, coverage gaps | `report-result` |
| Refresh ancestry, changed/new/deleted paths, feature slug | `select-scope`, modes, partial payload rules |

Intentional changes: omit the separate preflight ping because status already
checks connectivity; move `init` after approval because creating constraints is
a database write; validate the concrete payload before presenting it for final
confirmation. Revisions return to preparation and validation rather than silently
changing an approved payload. These are authoring-time dependencies, not a new
runtime permission system. The paper leaves enforced traversal to future work.
