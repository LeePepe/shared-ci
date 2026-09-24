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
| 4 `verify` | `.githooks/pre-push` (or pre-commit) and CI call the same executable `scripts/verify` | enforced | audit checks that `scripts/verify` is tracked with mode 100755, that the hook exists, is executable and calls it, and that ci.yml calls it | whether `core.hooksPath` is set locally (it cannot be seen in the tree) |
| 5 `ruleset` | The default-branch ruleset is code: [`templates/ruleset.json`](../templates/ruleset.json). It blocks deletion and non-fast-forward, requires a PR, requires `quality / aggregate` and `codex-review-target / codex-review` plus caller extras, requires code-owner review, allows no bypass actors, and uses strict=false unless the caller opts in. CODEOWNERS covers the important paths | enforced | audit checks that CODEOWNERS exists and covers `/.github/` and `/AGENTS.md`. [`scripts/ruleset/plan.py`](../scripts/ruleset/plan.py) computes old → new from the API dumps and keeps every existing required check unless `--map OLD=NEW` says otherwise. [`scripts/ruleset/apply.sh`](../scripts/ruleset/apply.sh) is a dry run by default; with `--apply` it applies the change and reads it back | the ruleset step itself: dry run, then Owner approval, then `--apply`, then readback (it needs admin API access) |
| 6 `pr_template` | `.github/pull_request_template.md` with the sections `Existing behaviour`, `Intent`, `Compatibility`, `Removed or weakened tests or policy`, `Test evidence` | guidance + enforced | audit checks that the template has every section. The `quality / aggregate` check fails a PR whose body is missing a section, leaves one empty or placeholder-only, or names a tested SHA other than the head | the Owner label for removed tests |
| 7 `dependencies` | Every shared library is declared in the `Dependencies` section of AGENTS.md with an exact version and a link to that version's `ai/` docs | guidance | audit checks each declared line for a `.../<version>/ai/` link, and compares it with the pins in `Package.resolved` and `package-lock.json` (a pin that is undeclared or has a different version is a finding) | other lockfile formats |
| 8 `identity` | No personal account names, credential-profile paths or local home paths | red line | audit scans every tracked text file for the `forbidden_patterns` | account names in prose that the patterns do not cover |

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
