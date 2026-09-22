# Context CLI contract (schema 1)

## Provenance and scope

The engine and six shell entrypoints derive from
[LeePepe/AIDash at 30092ed0d09e2b6e7a4a9f49d7cd64627fbf898e](https://github.com/LeePepe/AIDash/tree/30092ed0d09e2b6e7a4a9f49d7cd64627fbf898e/scripts/context).
The engine source blob is `8fbcba556fa83e54d04432e8ccf13e930656d4fc`; generic
fixture/ownership tests derive from `414fc541bd912a25bb4b667ad2bffbc78ebc52fe`.
Schemas, isolation tests and hardening are new shared-ci work. Product repository
assertions and hook tests were not extracted. No product ownership facts,
dependencies, red lines or gate commands live in the engine.

Requires Python 3.9+, Git and POSIX shell; no third-party Python libraries.
Invoke an entrypoint from anywhere inside the caller's Git worktree. Git selects
the root, independently of where shared-ci is installed. Relative file arguments
are root-relative, not current-directory-relative. This library does not clear
the caller's Git environment: a hook may intentionally select an index.
Test fixtures explicitly sanitize their child environments.

## Commands and outputs

| Entry | Successful output | Failure/status contract |
| --- | --- | --- |
| `audit` | One JSON summary: `{"ok":true,"classifications":{"leaf":N,"excluded":N,"total":N},"findings":0}` | 0 clean; 1 findings, each JSON finding on stderr |
| `resolve PATH… [--format json\|layer\|context]` | Default: one resolution JSON object per path; layer: one layer ID (blank for exclusions); context: one context path | 0 all resolved; 1 any per-path failure; continues through mixed inputs |
| `layers [PATH…] [--stdin] [--all] [--group GROUP] [--json]` | Sorted unique touched layer IDs; JSON array with `--json` | Mixed path errors: 1, remaining successes retained |
| `field LAYER FIELD` | Dotted lookup; strings printed literally; other values JSON with two-space indentation | Unknown layer/field: 2 |
| `contexts PATH…` | Root-to-leaf chain, one path per line; multiple paths prepend `PATH:` headings | Stops on first resolution error, status 2; preceding output retained |
| `run LAYER [--gate ID] [--mode local\|ci] [--path PATH]` | Gate log lines followed by inherited child stdout/stderr | See runner contract below |

`layers --all --json` returns an ordered object mapping layer IDs to context
paths (not an array). `--group` returns a sorted list/JSON array of members.
`--all` conflicts with paths and `--stdin`; `--group` conflicts with all three.
Positional paths and stdin may be combined. No paths (including empty stdin)
is an error. A valid exclusion-only query returns an empty list successfully.
An unknown or empty group is an error. Input resolution order is preserved by
`resolve` and `contexts`; only `layers` and tracked file enumeration sort.

Resolution JSON keys are `path, classification, layer, context, chain, reason`.
Classification is `leaf` or `excluded`; unused layer/reason is an empty string.
Inside-root absolute file paths are accepted and normalized to root-relative
paths, including absolute ancestor aliases such as `/tmp` for `/private/tmp`
and caller-owned symlink aliases. Nonexistent paths inside the root can resolve,
supporting deleted/anticipated files.

Context/validation errors outside the per-path and audit aggregation contracts
return 2 and emit a `context_error` finding. Ordinary argument parsing errors
retain argparse's usage/error stderr text and status 2; they are not JSON.
Findings always contain `layer, path, kind, detail, red_lines` as described by
`schemas/finding-v1.schema.json`. A gate's `--path` is diagnostic attribution,
not a gate filter; its spelling is preserved in failure output after containment
validation. Without it, failures name the leaf context.

## Context documents and ownership

`CONTEXT.md` starts with JSON frontmatter between `---` lines, followed by
freeform Markdown. `schemas/context-v1.schema.json` describes the draft2020-12
structure. Explicit `schema` must parse as Python integer 1 (not a boolean,
string or floating-point token such as `1.0`; this lexical check is stricter
than JSON Schema's mathematical integer type).
Omitted `schema` retains the fixed source's legacy schema-1 behavior; new callers
should write it explicitly. Unknown metadata remains available through `field`.
Recognized fields are type-checked; nulls are not implicit defaults. Runtime
validation is a purpose-built subset, not a general JSON Schema implementation.
Graph checks, containment, unique IDs, placeholder syntax and manifest comparisons
are additional semantic checks beyond the schema document.

An index has `kind: "index"`, optional `routes` and `exclusions` arrays, and no
leaf fields. A route requires string-list `patterns` and a `context` path, with
optional string-list `test_paths`. Exclusions require patterns and a nonblank
`reason`, including exclusions that currently match no tracked files.

A leaf has `kind: "leaf"`, nonblank `layer` and `parent`, and string-list
`scope`. Optional string lists: `test_paths, dependencies, dependents, red_lines`.
Optional `group` is a nonblank string. Omitted lists default to empty. Leaf
documents cannot contain index routes/exclusions. `parent` is root-relative;
route context paths are relative to the containing index directory.

Routing globs use POSIX separators: `*` and `?` do not cross directories;
`**` does, and `**/` matches zero or more directories. Pattern lists are
relative to the index directory. Leaf scope/test_paths mirror the parent route
exactly, including order. Test ownership participates in the same unique mapping
as implementation paths. Recursive queries reject unmapped/overlapping routes
and cycles. Audit also checks duplicate layer IDs, parent/scope/test-path
mismatches, missing dependencies, reciprocal dependency drift, dependency cycles
and manifest drift. Audit counts only Git-tracked files, never untracked files.

## Caller-owned manifests and dependency policy

An optional `manifest` has `kind`, root-relative `path`, and optional
`local_dependencies` string list. Supported adapters intentionally retain the
fixed source's narrow text parsing (they do not execute Swift or parse arbitrary
YAML):

- `swift-package`: matches literal `.package(path: "../Name")` dependencies.
- `xcodegen-target`: requires `target`, finds its conventional two-space
  target section and six-space `- package: Name` entries.

These adapters are drift checks for those textual forms, not complete language
parsers or dependency-security certification.

XcodeGen manifests may explicitly declare `external_dependencies`, an exact
string list subtracted before comparing observed packages to local dependencies.
There is no built-in package exception, wildcard interpretation, or implicit
external exclusion. Local and external lists must be disjoint; a nonempty
external list is invalid for the Swift-package adapter.

For example, a caller may declare:

```json
{"kind":"xcodegen-target","path":"project.yml","target":"Tool",
 "local_dependencies":["Core"],"external_dependencies":["NeutralVendor"]}
```

Migrating callers must explicitly copy their own existing external-dependency
policy into this metadata. Leaving it out does not silently suppress drift.

## Runner and containment

Gates have unique nonblank `id`, `kind: build|check|lint|test`,
`mode: local|ci|both`, and a nonempty array of nonblank command strings.
Every command string must encode as strict UTF-8 for the supported argv/logging
environment. Lone surrogate code points (including JSON-escaped high or low
surrogates) are rejected during validation of all declared gates, including
unselected gates, before any gate or placeholder-discovery subprocess. Valid
Unicode scalar values, including supplementary characters decoded from JSON
surrogate pairs, remain unchanged. Expanded arguments and rendered selected-gate
log lines are checked too, before execution, so a malformed log label cannot
cause partial execution. Errors use fixed printable labels and argument indices,
not the malformed string. This is a runtime semantic restriction beyond the
structural JSON Schema document, not a full JSON Schema implementation. UTF-8
stdio is the supported logging environment; arbitrary stream/I/O failures are
not an execution sandbox guarantee.
The default run mode is local. Declaration order is execution order;
`both` participates in either mode. All discovered context/gate shapes are
validated, including unselected gates, and duplicate layers/parent mismatches
are rejected before running.

Required execution fails closed (status 2) for no gates, no compatible gates,
an empty/unknown/unavailable `--gate`, malformed commands, unknown placeholders,
or empty expansion. All selected commands are expanded and path-checked before
any gate starts. Commands execute as argv with no implicit shell, cwd at root.
The only expansion tokens are whole arguments `{test_paths}` and
`{owned_python_paths}`; neither is permitted as the executable.
Braces are reserved in command tokens; move literal brace-bearing code into a
caller-owned script. Expansions are sorted tracked `.py` files resolved to the
selected leaf; test_paths additionally matches that leaf's test patterns.
An empty expansion never disappears into whole-repository discovery.

A missing/unlaunchable executable emits `gate_execution_failed` and returns 1.
Ordinary nonzero child status is propagated; a signalled child returns
`128 + signal` (SIGTERM = 143), with the raw negative subprocess status in its
`gate_failed` detail. Execution stops at the first child failure. These findings
carry the leaf's red lines. Successful runs retain the source log format:
`[context/run] LAYER:GATE — command arguments`.

Every input file, context route, leaf parent, manifest and expanded tracked path
is checked for lexical traversal and symlink containment before outside target
reads or execution. Root/child context and manifest symlink escapes fail, even
when their target exists. Internal symlinks are allowed; relative inputs keep
normalized logical names, while absolute inputs canonicalize internal symlinks
as in the fixed source. Explicit path-like command arguments, bare filename
symlinks, bare `..` arguments and repository executable paths are checked too.
All selected gates' raw arguments undergo preflight before placeholder expansion
can invoke discovery Git; expanded paths are checked before any gate subprocess.
An unsafe later gate prevents even an earlier safe gate from running.
Installed absolute executables (for example `/usr/bin/python3`) are allowed as
trusted caller configuration only when metadata inspection shows their path
never enters the canonical repository. This exception is exclusive to argv[0].
It does not apply to a repository executable spelled through an ancestor,
directory, file, or chained alias. Once a path enters the repository, remaining
traversal and symlinks must stay contained; an escape cannot become an installed
tool exception. The same check runs in both raw and expanded preflight.

Argument roles are checked as follows in both preflights:

| Position | Interpretation |
| --- | --- |
| `argv[0]` containing `/` | Executable pathname, always checked regardless of a leading `-`; only absolute paths may qualify for the installed-tool exception |
| Bare `argv[0]` | Command name using trusted caller PATH; local symlinks and bare `..` are still checked |
| Arguments before the first `--`, beginning with `-` | Opaque option tokens, including option-encoded values; not parsed as paths |
| Other arguments before `--` | Explicit paths with separators, bare `..`, and bare symlinks are checked |
| Every argument after the first `--` | Positional, even when beginning with `-`; the same path/symlink checks apply, and a later `--` is a positional name |

The option terminator itself is not a filename. This conventional delimiter
model is not a parser for each child program's option grammar: option-encoded
paths, inline programs, PATH lookup and child behavior remain trusted caller
configuration. Callers must use `--` when a dash-prefixed pathname is intended
as a positional argument. Explicit `.` arguments remain allowed; empty
placeholder expansion still fails rather than inventing whole-root discovery.

Absolute aliases require minimal link/ancestor metadata inspection outside the
canonical root. This performs no outside file-content reads or execution and
stops as soon as the canonical root is reached; the remaining components go
through the normal contained walk. Except for the installed argv[0] case above,
an alias that stays outside is rejected, as is traversal or a symlink that
leaves the root after entry, even if a later
component could re-enter. Relative internal symlink and logical-path behavior
is unchanged.

This is not an adversarial process sandbox: caller-authored gate code, installed
tools, environment and the selected worktree are trusted. Inline programs,
shells explicitly selected by callers, option-encoded filenames and child
behavior are not interpreted as a filesystem policy. Files must not be mutated
concurrently with validation/execution; checks are not a race-proof openat
sandbox. This slice provides neither runner isolation for untrusted products
nor independent CI/required-policy certification.

## Narrow development verification

Only synthetic disposable Git repositories and fixture-owned payloads execute.
The bare-parent regression places its `__main__.py` sentinel in a uniquely owned
temporary parent containing a nested fixture repository, never in a shared temp
directory or a real checkout's parent. Successful preflight prevents both that
sentinel and preceding selected gates from executing.
Executable-position regressions use fixture-owned executable sentinels and
markers, with positive controls for both contained aliases and external
installed-tool paths. No product executable or real outside data is used.
Fixtures remove inherited Git routing/index/object/config overrides in child
environments, ignore global/system config, use an empty template, bound
subprocess waits to 10 seconds, and clean up only their unique temporary roots.
They do not repurpose HOME/CODEX_HOME or edit the parent's environment.

```sh
/usr/bin/python3 -I -B -m unittest discover -s tests/context -p test_resolution.py -v
/usr/bin/python3 -I -B -m unittest discover -s tests/context -p test_cli_contract.py -v
/usr/bin/python3 -I -B -m unittest discover -s tests/context -p test_runner.py -v
for entry in audit resolve layers field contexts run; do
  /bin/sh -n "scripts/context/$entry" || exit
done
git diff --check
```

Passing these tests is development evidence only. Publication, merge, release,
R0/C1/real-caller proof, trusted required policy and full delivery certification
remain separate gates.
