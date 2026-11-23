---
name: verify-changed
description: Plan and run verification for the current branch's changes using the cross-repo feature graph in Neo4j, which it only reads. Finds the affected features, the tests and manual checks, and other repos that consume or provide the interfaces you touched. Then runs this repo's tests. Use before opening a PR or when asked what a change affects.
argument-hint: "[base-ref] [--plan-only]"
---

# verify-changed

This skill reads the feature graph that `/feature-graph` builds and turns the current diff into a verification plan. Then it runs the local tests in that plan.

**It never writes to the graph.** It uses only `graph.py impact`, `status` and `read`. `read` runs in a transaction that is always rolled back, and it fails if a statement tries to write. If the user wants the graph updated, tell them to run `/feature-graph refresh`.

## Setup

- `G=<this skill's base directory>/../feature-graph/scripts/graph.py`. Run it as `python3 -I "$G" ...`.
- Env: `NEO4J_URI`, plus `NEO4J_READ_USERNAME`/`NEO4J_READ_PASSWORD` (preferred, a read-only DB user) or `NEO4J_USERNAME`/`NEO4J_PASSWORD`.
- If `ping` fails, say why, and fall back to a plan built only from the diff (step 5).

## 1. Changed files

```sh
python3 -I "$G" whoami
BASE=${ARG_BASE:-$(git merge-base origin/<default_branch> HEAD)}
{ git diff --name-only "$BASE"...HEAD; git diff --name-only HEAD; git ls-files --others --exclude-standard; } | sort -u > "$SCRATCH/changed.txt"
```

Fetch `origin/<default_branch>` first if it is missing. Drop files that were deleted on the branch from the test step, but keep them in the impact query, because their features are still affected. If there are no changes, say so and stop.

## 2. Query the graph

```sh
python3 -I "$G" impact --files-from "$SCRATCH/changed.txt"
```

The JSON returned contains:
- `mapped`, `mapped_sha`: if `mapped` is false, the repo has never been mapped. Say so, recommend `/feature-graph`, and go to step 5.
- `unmapped_files`: changed files the graph does not know about.
- `features`: affected features, each with `via` (the changed files and their roles).
- `dependents`: features in this repo that depend on the affected ones.
- `interfaces`: interfaces touched by the changed files (`level: direct`) or by other files of the affected features (`indirect`). Each one lists `counterparts`, the files and features **in other repos** on the other side.
- `checks`: test and manual checks for affected features, dependents and counterpart features, including checks in other repos.
- `requires.outgoing`: repos this one needs for a full test. `requires.incoming`: repos that need this one.

Also check staleness: run `git rev-list --count <mapped_sha>..HEAD`. If `mapped_sha` is not an ancestor of HEAD, say that the map comes from a different line of history.

## 3. Write the plan (in chat)

Look at the actual diff of files that touch an interface (`git diff "$BASE" -- <file>`) to decide whether the **shape** of the interface changed: a route, params, response fields, message payload, or table columns. Keep it brief:

```
## Verification plan — <repo> @ <short sha> (graph mapped at <short mapped_sha>, N commits behind)

### Affected features
- <name> (<kind>) — via <file> [<role>]
  - also affects: <dependent feature> (depends on it via <via>)

### Run here
- `<deduplicated test command>`         ← runs in step 4
- Manual: <manual check description>

### Other repos
| Repo | Why | Action |
|---|---|---|
| 84codes/account-console | exposes `http:POST /api/instances` that <file> calls; you changed the request body | **may need a change** + run `<their check command>` |
| 84codes/machines | consumes `amqp:amq.topic/instance.created` that you publish | run `<check>`; verify payload compatibility |
| 84codes/account-console | required for e2e (declared: <reason>) | have it running for manual checks |

### Gaps
- Unmapped files: <list>, or "none"
- Graph is N commits behind, so run `/feature-graph refresh` (only if N > 0 and the gaps matter)
```

How to fill the Action column:
- You changed the shape of an interface you **expose**, and another repo **consumes** it: **may need a change** in that repo, and run its checks.
- You changed how you **consume** an interface that another repo **exposes**: check that the provider supports the new call, and run its checks if you depend on new behavior.
- The interface was touched but its shape did not change: **run their checks** (low priority), or leave the repo out if the change is clearly internal.
- `requires.outgoing`: list the repo as needed for e2e. `requires.incoming`: mention it only when you changed an exposed interface.

## 4. Run local tests

Skip this step if the user passed `--plan-only`.

- Take the `test` checks where `repo` is this repo. Merge commands that share a runner into one invocation, e.g. one `bundle exec rspec a_spec.rb b_spec.rb` built from the union of `paths`. Add spec files that are themselves in the changed list.
- Drop paths that no longer exist.
- Run them. If the toolchain or services are missing (no bundle, DB not running), report the exact error and the command the user should run. Do not try to set up the environment unless the user asks.
- Report pass or fail per command, with the failing examples. Never run checks in other repos. List them as commands for the user.

## 5. Fallback (no graph, or repo not mapped)

Build a best-effort plan from the diff alone. Find specs whose names mirror the changed files (`app/x/foo.rb` → `spec/x/foo_spec.rb`), and grep the diff for routes, HTTP clients, `publish(` and env-var URLs to flag possible cross-repo effects. Label the plan clearly as **not graph-backed**, and recommend `/feature-graph`.
