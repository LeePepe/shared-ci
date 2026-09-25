# Minimum repository contract (v1)

Every repository that consumes shared-ci satisfies these eight items. An agent
that knows nothing else about the repository can still follow them. The
machine-readable form, including the section names, limits and forbidden
patterns that the checker uses, is
[`schemas/repo-contract-v1.json`](../schemas/repo-contract-v1.json) (`x-contract`).

`scripts/context/audit` runs these checks whenever the repository uses the
repo-kit layer map (a root `docs/architecture/tech-context.md` or
`tech-context.md`, and no legacy root `CONTEXT.md`). The `contract` lane of
`quality.yml` runs the same audit in CI. Findings use the
[finding schema](../schemas/finding-v1.schema.json), with `layer: "contract"`
and `kind: "contract_<item>"`.

| # | Item | Type | Machine check | Doc-only remainder |
| --- | --- | --- | --- | --- |
| 1 `agents` | `AGENTS.md` of at most 150 lines. Required sections: `Read first`, `Protocol`, `Verify`, `Required checks`, `Red lines`, `Delivery`. The protocol pointer is `LeePepe/shared-ci@<40-char SHA>/ai/agent-protocol.md` | guidance | audit checks that the file exists, the line count, the sections, that the pointer is a full SHA, and that the pointer SHA matches every `uses: LeePepe/shared-ci/...@` pin | whether the content is accurate |
| 2 `agent_files` | `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md` and `.cursorrules` only say "read AGENTS.md first", plus 1–2 notes specific to that tool | guidance | audit checks that each file refers to AGENTS.md, has at most 12 non-empty lines, does not repeat the shared-ci pin, and does not repeat any required-check name listed in AGENTS.md | whether the notes contradict AGENTS.md |
| 3 `ci` | `.github/workflows/ci.yml` calls `LeePepe/shared-ci/.github/workflows/quality.yml@<40-char SHA>` and passes this repository's commands | enforced | audit checks that ci.yml calls quality.yml, that every pin is a full SHA, and that all pins are the same SHA. workflow-lint also rejects tag and branch refs and self-hosted jobs without a fork guard | — |
| 4 `verify` | `.githooks/pre-push` (or pre-commit) and CI call the same executable `scripts/verify`. With `changed-only: true` CI calls `scripts/verify --selected`, which runs the layers the `select` job chose, or every layer on a full run | enforced | audit checks that `scripts/verify` is tracked with mode 100755, that the hook exists, is executable and calls it, and that ci.yml calls it | whether `core.hooksPath` is set locally (it cannot be seen in the tree) |
| 5 `ruleset` | The default-branch ruleset is code: [`templates/ruleset.json`](../templates/ruleset.json). It blocks deletion and non-fast-forward, requires a PR, requires `quality / aggregate` and `codex-review-target / codex-review` plus caller extras, requires code-owner review, allows no bypass actors, and uses strict=false unless the caller opts in. CODEOWNERS covers the important paths | enforced | audit checks that CODEOWNERS exists and covers `/.github/` and `/AGENTS.md`. [`scripts/ruleset/plan.py`](../scripts/ruleset/plan.py) computes old → new from the API dumps and keeps every existing required check unless `--map OLD=NEW` says otherwise. [`scripts/ruleset/apply.sh`](../scripts/ruleset/apply.sh) is a dry run by default; with `--apply` it applies the change and reads it back | the ruleset step itself: dry run, then Owner approval, then `--apply`, then readback (it needs admin API access) |
| 6 `pr_template` | `.github/pull_request_template.md` with the sections `Existing behaviour`, `Intent`, `Compatibility`, `Removed or weakened tests or policy`, `Test evidence` | guidance + enforced | audit checks that the template has every section. The `quality / aggregate` check fails a PR whose body is missing a section, leaves one empty or placeholder-only, or names a tested SHA other than the head | scope and review routing under the agent protocol; ordinary test-code changes do not themselves require Owner approval |
| 7 `dependencies` | Every shared library is declared in the `Dependencies` section of AGENTS.md with an exact version and a link to that version's `ai/` docs | guidance | audit checks each declared line for a `.../<version>/ai/` link, and compares it with the pins in `Package.resolved` and `package-lock.json` (a pin that is undeclared or has a different version is a finding) | other lockfile formats |
| 8 `identity` | No personal account names, credential-profile paths or local home paths | red line | audit scans every tracked text file for the `forbidden_patterns` | account names in prose that the patterns do not cover |

## PR scope

PR size is controlled by a bounded responsibility area, not a universal line
or file ceiling. The task and PR's existing `Intent` section carry the scope
used by the [agent protocol](agent-protocol.md#2-scope):

| Field | Evidence |
| --- | --- |
| Purpose and primary area | One acceptance result; a code layer, CI, docs, reviewer rules or another existing ownership area |
| Allowed paths and non-goals | Specific files or bounded directories, including necessary tests/docs; no repository-wide catch-all |
| Layer ownership and dependencies | Existing layer map, support-path purpose and any inseparable cross-area companions |
| CI verification | Required checks and dependency-affected verification from the actual diff, retaining forced full runs |
| Review responsibilities | Assigned Reviewer responsibilities and any Owner-only matters under trusted policy/CODEOWNERS |

Compare the complete diff against the original task, including both paths of
a rename (`git diff --name-status --no-renames origin/main...HEAD`; use the
actual base). Inspect pending changes too before the final push. An allowed
path alone does not justify an unrelated change within it. Files, lines and
labels cannot establish scope or reduce required review.

**Enforcement boundary:** the current resolver classifies paths, changed-layer
selection chooses affected tests, and the aggregate validates enabled lanes
and PR-body evidence. None compares the diff to a task path allowlist or proves
single-purpose scope. That check currently belongs to workflow/diff review;
a mechanical scope-admission check is separate implementation work, not supplied
by this documentation change. CI running dependent layers does not authorize
editing them. A support-only selection is not approval to mix arbitrary docs
or to treat Markdown policy as ordinary documentation.

No workflow, schema, pin or server protection changes here. Consumers follow
the protocol version they pin; publishing these rules does not deploy them to
existing consumers or installed roles.

## Changed-layer selection (optional)

A caller may set `changed-only: true` on `quality.yml`, and may call
`select.yml` for its own lanes, to run only the layers a PR touches plus
their dependents. Required checks must still always report. A lane that is
not selected runs a step that prints `not selected: <reason>` and succeeds.
It is never skipped by a job-level `if`. Anything doubtful is a full run.
[`docs/changed-layer-selection.md`](../docs/changed-layer-selection.md) is
the contract. The aggregate records the selection. Selection does not change
any of the eight items.

## Using the checks

```sh
# from the caller root, with shared-ci checked out at the pinned SHA
python3 <shared-ci>/scripts/context/_context.py audit      # layer map and contract
python3 <shared-ci>/scripts/lint/workflows.py --root .     # workflow-lint
```

```sh
# item 5: plan (dry run), Owner approves the printed old -> new, then apply + readback
scripts/ruleset/apply.sh OWNER/REPO --map 'old-check=quality / aggregate'
scripts/ruleset/apply.sh OWNER/REPO --map 'old-check=quality / aggregate' --apply
```

Templates for every item are in [`templates/`](../templates/). Repositories
that still use the legacy recursive `CONTEXT.md` tree keep the earlier audit
behaviour unchanged. They opt into the contract by moving to the repo-kit layer
map.

## Exceptions

This contract has no self-service exceptions. The Owner must approve a
deviation, and it is recorded under `Red lines` in AGENTS.md, which is covered
by CODEOWNERS. Any change to this file, the schema or the checker is an
important PR.
