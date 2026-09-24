# Changed-layer CI selection (v0.2.0)

`scripts/verify` already picks layers from the local diff. CI does the same
when the caller opts in with `changed-only: true`, and it must never make a
required check disappear: GitHub waits forever on a required job that was
skipped at job level. So selection has three parts: a selector that fails
closed, lanes that always report, and an aggregate that knows the difference.

## 1. Selector

[`scripts/select/layers.py`](../scripts/select/layers.py) runs in the `select`
job of [`quality.yml`](../.github/workflows/quality.yml) and in the reusable
[`select.yml`](../.github/workflows/select.yml), both at the pinned SHA.

1. Changed files: `git diff --name-only --no-renames merge-base(base, head)..head`
   for `pull_request` / `pull_request_target`. Renames count old and new path.
2. Each path goes through the pinned resolver (`scripts/context resolve`). A
   `leaf` path touches its layer; a `support` (excluded) path touches none.
3. A changed file that a layer's gate names literally in its argv (for
   example `python3 scripts/tests/test_app_startup.py`) touches that layer,
   even when the file is a support path.
4. Every transitive dependent is added: if `B.depends_on` contains `A` (or `A`
   declares `depended_by: [B]`) and `A` is touched, `B` runs too.

**Full run** (every layer, `full=true`) when any of these holds:

| Trigger | Why |
| --- | --- |
| Event is not a pull request (push to the default branch, `schedule`, `workflow_dispatch`, `merge_group`, anything else) | The default branch always proves the whole tree |
| A changed path is unmapped (resolver error for that path) | Nobody owns it, so nobody can say what it affects |
| A dependency manifest or lockfile (`Package.swift`, `Package.resolved`, `package.json`, lockfiles, `pyproject.toml`, `requirements*.txt`, `go.mod`, `Cargo.toml`, Gradle, Podfile, toolchain version files, …) | A dependency change can break any layer |
| `.github/**`, `scripts/verify`, `scripts/ci/**` | CI wiring decides what runs |
| A layer-map document (`**/tech-context.md`, `**/CONTEXT.md`) | Ownership and `depends_on` may have changed |
| An AGENTS.md line with a shared-ci pin is added or removed | The gate itself changed |
| A caller pattern from the `force-full-paths` input | Repository-specific risk |
| Base/head SHA missing, git error, resolver or layer-map error | When in doubt, run everything |

The selection is computed over the **whole PR** (merge-base to head), never
the last push, so a follow-up commit cannot drop lanes an earlier commit needs.

**Empty diff and support-only diff** (for example docs only): no layer is
selected (`full=false`, `any_layer=false`, `layers=[]`). The layer lanes
short-circuit; `contract` (layer map + repository contract) and
`workflow-lint` always run, and the aggregate still checks the PR body.

Outputs (`select.yml` and `quality.yml`'s `select` job):

| Output | Value |
| --- | --- |
| `full` | `true` / `false` |
| `any-layer` | `true` when at least one layer runs (always `true` when `full`) |
| `layers` | JSON list of selected layer IDs (every layer when `full`) |
| `layers-space` | the same, space separated |
| `reason` | one line, e.g. `changed layers: VoxDomain; dependents: VoxApplication, …` |
| `selection` | full JSON record: mode, event, base, head, layers, triggers, changed/unmapped paths (capped at 200 each, with exact `*_count`) |

## 2. Required-check-safe lanes

A lane that a ruleset requires must **always run and report**. Never put the
selection in a job-level `if`. Decide inside the job:

- the job's own `if` only keeps what it had before, plus `!cancelled()` so it
  still runs when `select` failed;
- the first step computes `run`: `false` only when `needs.select.result ==
  'success'`, `full == 'false'` and the lane's layer is not in `layers`;
  otherwise `true` (so a failed or missing selection runs the lane in full);
- when `run` is `false`, the step prints `not selected: <layer> (<reason>)`
  and every later step is skipped by `if: steps.lane.outputs.run == 'true'`.
  The job then ends `success` under the same check name;
- when `run` is `true`, the steps are exactly the ones the lane had before.

In `quality.yml` the verify/lint/build/test lanes follow this pattern (they
short-circuit only when **no** layer is selected; when some are, the command
gets `CI_SELECTED_LAYERS` and `CI_SELECTION_FULL` and runs, and
`scripts/verify --selected` from the template runs just those layers). A
short-circuited lane moves to `ubuntu-latest` because it only prints a line.

Matrix callers keep the matrix unconditional: every leg expands, and each leg
checks its own membership at step level.

```yaml
jobs:
  select:
    uses: LeePepe/shared-ci/.github/workflows/select.yml@<same-40-char-sha>

  spm:
    name: SPM ${{ matrix.package }}        # required check names stay the same
    needs: select
    if: "!cancelled()"
    runs-on: macos-26
    strategy:
      fail-fast: false
      matrix:
        package: [Core, App]
    steps:
      - id: lane
        env:
          SELECT_RESULT: ${{ needs.select.result }}
          FULL: ${{ needs.select.outputs.full }}
          LAYERS: ${{ needs.select.outputs.layers-space }}
          REASON: ${{ needs.select.outputs.reason }}
          LAYER: ${{ matrix.package }}
        run: |
          run=true
          if [ "$SELECT_RESULT" = "success" ] && [ "$FULL" = "false" ]; then
            case " $LAYERS " in *" $LAYER "*) ;; *) run=false; echo "not selected: $LAYER ($REASON)" ;; esac
          fi
          echo "run=$run" >> "$GITHUB_OUTPUT"
      - if: steps.lane.outputs.run == 'true'
        uses: actions/checkout@<sha>
      - if: steps.lane.outputs.run == 'true'
        run: scripts/verify --layer ${{ matrix.package }}
```

A lane that must not become required-and-silent (for example an optional
simulator lane) may use a job-level `if` on the selection; it is not required,
so a skip is harmless.

## 3. Aggregate

The aggregate needs `select` too. Each lane reports a `ran` output (`true`
when its real steps executed). With a selection present, the gate
([`gate.py`](../scripts/quality/gate.py)) keeps every v0.1.0 rule and adds:

- the `select` job must be `success`, and a changed-only selection must be
  for the expected head SHA; a missing or unparseable selection fails;
- `contract` and `workflow-lint` can never short-circuit;
- a layer lane may short-circuit only when the selection has no layer
  (`any_layer=false`); otherwise it must have run;
- a short-circuited lane must still be `success` with the head SHA;
- unselected lanes stay `success|skipped`.

The aggregate output and the job summary record the selection (`mode`,
`full`, `layers`, `reason`, `head`) and list the `short_circuited` lanes.

## Compatibility

`changed-only` defaults to `false`. Then `select` runs in `disabled` mode
(`full=true`, the diff is not read), every lane has `ran=true`, and the gate
behaves as in v0.1.0. v0.1.0 callers keep working with no edits; their
`quality / aggregate` check name is unchanged. The one visible difference is
a new `quality / select` job in the run.
