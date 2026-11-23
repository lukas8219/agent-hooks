# Verification plan

Here `BASE` means `changes.merge_base` from the change collector.

Look at the actual diff of files that touch an interface (`git diff "$BASE" -- <file>`) to decide whether the **shape** of the interface changed: a route, params, response fields, message payload, or table columns. Keep it brief:

```
## Verification plan — <repo> @ <short sha> (graph mapped at <short mapped_sha>, N commits behind)

### Affected features
- <name> (<kind>) — via <file> [<role>]
  - also affects: <dependent feature> (depends on it via <via>)

### Run here
- `<deduplicated test command>`         ← runs in run-local-tests
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
