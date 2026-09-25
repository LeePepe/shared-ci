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
| 1 `agents` | `AGENTS.md` is a directory of at most 150 lines. Required sections: `Read first`, `Protocol`, `Verify`, `Required checks`, `Red lines`, `Delivery`; these point to authoritative documents/configuration. The protocol pointer is `LeePepe/shared-ci@<40-char SHA>/ai/agent-protocol.md` | guidance | audit checks that the file exists, the line count, the sections, that the pointer is a full SHA, and that the pointer SHA matches every `uses: LeePepe/shared-ci/...@` pin | pointer accuracy and directory-only content |
| 2 `agent_files` | `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md` and `.cursorrules` only say "read AGENTS.md first", plus 1–2 notes specific to that tool | guidance | audit checks that each file refers to AGENTS.md, has at most 12 non-empty lines, does not repeat the shared-ci pin, and does not repeat any required-check name listed in AGENTS.md | whether the notes contradict AGENTS.md |
| 3 `ci` | `.github/workflows/ci.yml` calls `LeePepe/shared-ci/.github/workflows/quality.yml@<40-char SHA>` and passes this repository's commands | enforced | audit checks that ci.yml calls quality.yml, that every pin is a full SHA, and that all pins are the same SHA. workflow-lint also rejects tag and branch refs and self-hosted jobs without a fork guard | — |
| 4 `verify` | `.githooks/pre-push` (or pre-commit) and CI call the same executable `scripts/verify`. With `changed-only: true` CI calls `scripts/verify --selected`, which runs the layers the `select` job chose, or every layer on a full run | enforced | audit checks that `scripts/verify` is tracked with mode 100755, that the hook exists, is executable and calls it, and that ci.yml calls it | whether `core.hooksPath` is set locally (it cannot be seen in the tree) |
| 5 `ruleset` | The default-branch ruleset is code: [`templates/ruleset.json`](../templates/ruleset.json). It blocks deletion and non-fast-forward, requires a PR, requires `quality / aggregate` and `codex-review-target / codex-review` plus caller extras, requires code-owner review, allows no bypass actors, and uses strict=false unless the caller opts in. CODEOWNERS covers the important paths | enforced | audit checks that CODEOWNERS exists and covers `/.github/` and `/AGENTS.md`. [`scripts/ruleset/plan.py`](../scripts/ruleset/plan.py) computes old → new from the API dumps and keeps every existing required check unless `--map OLD=NEW` says otherwise. [`scripts/ruleset/apply.sh`](../scripts/ruleset/apply.sh) is a dry run by default; with `--apply` it applies the change and reads it back | the ruleset step itself: dry run, then Owner approval, then `--apply`, then readback (it needs admin API access) |
| 6 `pr_template` | `.github/pull_request_template.md` with the sections `Existing behaviour`, `Intent`, `Compatibility`, `Removed or weakened tests or policy`, `Test evidence` | guidance + enforced | audit checks that the template has every section. The `quality / aggregate` check fails a PR whose body is missing a section, leaves one empty or placeholder-only, or names a tested SHA other than the head | review routing under the agent protocol; ordinary test-code changes do not themselves require Owner approval |
| 7 `dependencies` | Every shared library is declared in the `Dependencies` section of AGENTS.md with an exact version and a link to that version's `ai/` docs | guidance | audit checks each declared line for a `.../<version>/ai/` link, and compares it with the pins in `Package.resolved` and `package-lock.json` (a pin that is undeclared or has a different version is a finding) | other lockfile formats |
| 8 `identity` | No personal account names, credential-profile paths or local home paths | red line | audit scans every tracked text file for the `forbidden_patterns` | account names in prose that the patterns do not cover |

## Opt-in metadata and directory audit

Callers with `.github/repo-contract.json` opt into the directory-only audit
below. Callers without metadata retain the existing v1 sections, protocol-pointer
and dependency checks in the table above. Invalid or untracked metadata fails
closed; it never falls back to a valid legacy AGENTS file. The eight report
items and finding schema remain unchanged.

The [metadata schema](../schemas/repo-metadata-v1.json) requires exactly `schema`,
`guide`, `shared_ci` and `dependencies`. `schema` is integer `1`; `shared_ci` is
one lowercase full 40-character provider SHA matching every workflow pin.
`guide` names a tracked readable repository-relative document containing
`Protocol`, `Verify`, `Required checks`, `Red lines` and `Delivery` sections.
`dependencies` maps library names to exactly `version` and `ai`: an exact semver
(optional `v` prefix, ASCII identifiers, prerelease and build metadata; numeric
core/prerelease identifiers have no leading zeros) or lowercase full SHA, and an
HTTPS link containing `/<version>/ai/`. Shared-ci has only
one authority, `shared_ci`, and cannot also appear in `dependencies`. Supported
lockfiles retain their parity checks; an unreadable tracked lockfile fails.

In this mode, AGENTS contains headings, blank lines and conditional Markdown
links only, at most 150 lines, with a local route to the declared guide. Each
entry is one inline link, optionally preceded by a list marker and a condition
ending in `:`, and optionally followed by `.` or `;`. Inline commands and policy
prose belong in linked authoritative documents instead. Required-check duplication
in tool-specific agent files is checked against the guide rather than the index.
Review callers must pass that guide as `rules-file`; this checks configuration,
not whether a live runner or required AI review has been enabled.

Workflow pin parity and review routing share one parsed job/step call inventory,
not a text search. Block mappings, quoted keys/scalars and nested flow mappings
are supported. Every tracked workflow is read as a regular file and parsed;
unreadable files, malformed shapes and unsupported YAML fail the audit explicitly.
The stdlib YAML subset rejects anchors/aliases, tags, multi-document streams,
complex or escaped mapping keys and multiline flow collections. Shell text is
not interpreted as workflow configuration.

### Directory routes and protection

Local targets are repository-root-relative; a fragment alone refers to AGENTS.
Percent-encoded UTF-8 paths/fragments are decoded once. Malformed escapes, empty
fragments, query strings, parent traversal and absolute paths fail. Metadata,
AGENTS, the guide and local targets must have an unconflicted regular-file index
entry (`100644` or `100755`) and be readable in the worktree. File or ancestor
symlinks are rejected before reading; untracked local files cannot satisfy a
route. This validates the worktree, not committed-content identity or concurrent
hostile mutation. Git filenames used by identity scanning remain distinct from
the narrower route syntax, including tabs, newlines, quotes and backslashes.

Fragments on `.md`/`.markdown` resolve to block ATX or Setext headings, or explicit
HTML `id`/`<a name>` anchors. Heading slugs lowercase Unicode letters, remove
punctuation and inline markup, retain hyphens/underscores, replace spaces with
hyphens, and suffix duplicates with `-1`, `-2`, etc. Inline code contributes its
displayed text; explicit anchors are case-sensitive. Code examples, comments,
frontmatter and raw HTML block headings do not create heading anchors. This is
a bounded reader, not a full Markdown renderer: container headings, custom
heading attributes and renderer extensions are unsupported; use a standalone
explicit anchor instead. Other file types cannot satisfy fragments. HTTPS
pointers are not fetched or remotely fragment-validated.

CODEOWNERS must retain the existing required patterns and an exact `/<guide>`
pattern. The highest-priority tracked CODEOWNERS file is authoritative, even
when empty. Effective last-match ownership of AGENTS, metadata and the guide is
checked, so later ownerless overrides fail. Unsupported ownership patterns fail
closed rather than claiming complete GitHub pattern support. Owner tokens must
be supported `@user`, `@organization/team` or email forms; malformed tokens fail
explicitly, even alongside a valid owner. Email support is ASCII dot-atom local
parts and DNS-style domains; exotic forms are rejected rather than guessed.
Syntactic admission does not prove identity existence, visibility or write access;
live server protection still needs independent readback.

### Adoption boundary

This support does not migrate templates, bootstrap scripts, caller pins or this
repository's own AGENTS automatically. Adopt only after the provider change is
reviewed and available at a fixed SHA. A separate reviewed consumer migration
must coordinate the workflow pin, metadata, guide/index, metadata-aware bootstrap,
review `rules-file` and guide CODEOWNERS, preserving required checks. Old fixed
providers do not acquire metadata support retroactively. A versioned protocol
route may remain for compatibility, but its SHA must match metadata.

Rollback reverts the consumer's coordinated references/configuration to its
recorded compatible baseline; it does not rewrite provider tags or waive gates.
Existing repository layer/PR rules below apply in both contract modes. This
change neither adds a test-loss gate nor changes ordinary-test approval policy.

## Repository development contract

The repository defines its architecture and PR boundaries before a task is
planned. They apply to every contributor, independently of the agent or workflow.
Shared-ci supplies the format, reusable checks and templates; repo-kit adapts
them to the repository's actual structure. Planner and implementers consume this
contract, not invent a new layer model or PR policy for each assignment.

| Repository artifact | Owns |
| --- | --- |
| Root `tech-context.md` | Layer inventory, dependency graph and reasoned support paths |
| Each layer's `tech-context.md` | Responsibility, owned implementation/tests, interfaces, allowed dependencies and verification |
| Development guide (normally `docs/development.md`) | PR work units, permitted companion changes, development/verification entry points and review routing |
| Scripts, caller CI and CODEOWNERS | Executable project checks and effective review protection |
| `AGENTS.md` | Task-oriented pointers to those sources, not copies of their rules |

### Define layers by responsibility

- A layer is a stable code responsibility with explicit interfaces and allowed
  dependencies. Packages/targets are evidence, not an automatic one-to-one rule:
  one package may contain domain, state and presentation layers. Do not create
  temporary layers just to fit a task or PR, or impose one stack's layer names
  on every repository.
- Use the existing [tech-context format](../docs/context-cli-contract.md#simplified-tech-context-layer-map-repo-kit-format):
  unique layer ID, root-relative `owns`, `depends_on`, verification `gate` and
  `red_lines`. Put tests under the layer they exercise even when stored elsewhere.
  Explain responsibilities, public interfaces and excluded concerns in the leaf.
- Every tracked path resolves to one layer or one explicit support declaration;
  the root table and leaf dependencies agree and form an acyclic graph. Support
  means non-layer material, not unverified material: name its purpose and checks.
  Broad script/source exclusions must not hide executable modules from ownership.
- Actual import/API boundaries need the repository's own lint/build/tests,
  wired through its verification commands. The shared resolver checks declared
  ownership/dependencies, not arbitrary language imports. Record missing checks
  as gaps rather than claiming the declarations prove the implementation.

### Define PR work units in the repository

The development guide names the repository's PR units and, for each, references
its layer/path source, allowed companion changes, verification and review policy.
Use [the guide template](../templates/development.md) with actual repository paths.
Code units refer to existing layer IDs; CI wiring, documentation/spec work and
review/policy changes use their own supporting responsibilities, not fake layers.

- One PR delivers one independently acceptable purpose within one such unit.
  Independent requirements/spec work stay separate even within the same layer.
  Required tests and implementation documentation travel with their code;
  unrelated docs cleanup, CI changes or review-policy changes do not.
- Cross-layer features become dependency-ordered PRs using the repository's
  interfaces and permitted companion paths. Keep every step buildable/testable;
  redesign the sequence if it cannot stand alone. A needed architecture or PR
  boundary change is an explicit contract change under existing review policy,
  not an implementer widening a label or a Planner inventing another layer.
- The PR's existing `Intent` names the repository unit and the requirement/spec
  or task when present. A direct agent needs no Dev Team task graph to follow
  this contract. There is no separate author-defined path-allowlist form.
- There is no universal line/file ceiling. Markdown, tests and support paths
  do not determine approval by extension; actual policy/gate/permission changes
  remain protected under the [protocol](agent-protocol.md#6-important-prs-need-the-owner).

### Checks and review have distinct jobs

| Responsibility | Enforcement |
| --- | --- |
| Tracked-path coverage, overlaps, declared dependencies/cycles and table drift | Existing context audit / CI contract lane |
| Real import boundaries, builds and behaviour | Repository-declared lint/build/test commands; local hooks and CI use the same entry |
| Check selection and current-head evidence | Existing layer selection and aggregate; retain forced full runs and all required checks |
| One purpose, appropriate PR unit and necessary companion changes | Existing planning/code review using the repository guide; not a new PRM scope report |

Record `enforced`, `manual`, `planned` or `N/A` with the actual command/evidence
for each repository rule. The current aggregate does not infer PR purpose or
validate the guide's PR-unit table; do not claim those are mechanical checks.
PRM consumes existing CI/review outcomes and manages delivery, not PR size.
Updating this source does not deploy consumer pins, roles, directory-only
schema/audit migrations or server protections.

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
deviation; record it in an existing CODEOWNERS-protected policy document and
keep only its pointer under `Red lines` in AGENTS.md. Any change to this file,
the schema or the checker is an important PR.
