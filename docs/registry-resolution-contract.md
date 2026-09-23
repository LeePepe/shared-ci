# Committed registry resolution v1

This development candidate resolves authoritative documents and capability
descriptions from an externally admitted Git-source distribution. It is not an
importer, policy selector, installer, gate runner or authentication mechanism.
Implementation and isolated test sources are authored; new tests are **NOT RUN**.
Required CI, real callers, recovery and full 6DQ remain separate obligations.

## CLI

The public Interface has one operation, from any caller working directory:

```sh
"$ADMITTED_PYTHON" -I -S -B "$PROVIDER_DIR/scripts/contracts/resolve.py" \
  --git "$ADMITTED_GIT" --revision "$PROVIDER_REVISION" --entry task.upgrade
```

Tools are externally supplied absolute executable paths. Revision is an
already-existing nonzero lowercase 40-hex commit ID. Entry IDs match
`[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*`. Both `--option value` and `--option=value`
work. No positionals, abbreviations, duplicates, overrides, overlays, output-file
options, aliases, wildcards, floating selections or fallback are supported.

`-h` or `--help` alone prints help to stdout and exits 0 without provider/Git
access. Combining help with anything else is an argument error.

| Outcome | stdout | stderr | Exit |
| --- | --- | --- | --- |
| Success | One complete result JSON plus LF | Empty | 0 |
| Resolution failure | Empty | One finding JSON plus LF | 1 |
| Argument error | Empty | Usage line and one error line | 2 |

Fixed usage: `usage: resolve.py --git ABSOLUTE_GIT --revision FULL_SHA --entry ENTRY_ID`.
Argument checks scan left-to-right for unknown/positional tokens, duplicates and
missing values; then missing required options in git/revision/entry order; then
invalid values in that order. Unknown but syntactically valid IDs fail resolution.
JSON uses UTF-8, sorted keys, compact separators and exactly one trailing LF.
Validation finishes before success output. Broken streams, forced termination
and interpreter startup failure are outside the structured guarantee, not success.

## Tool admission

Before execution, an external launcher/reviewer establishes the expected
repository identity and existing commit; actual identities of absolute Git,
Python and any shell/example tools; a supported complete offline distribution;
executing resolver bytes equal its committed blob; example bytes/mode equal the
commit before executing it; and no concurrent mutation. Distribution metadata,
including repository-local configuration, must not redirect outside that offline
distribution. Absolute paths and internal byte comparisons are not authentication.

Runtime dependencies are Python 3.9+ stdlib and admitted Git supporting SHA-1
object-format inspection. `-I -S -B` excludes caller Python paths, site startup
and bytecode writes. Git children use explicit provider Git-directory/worktree
arguments and a newly constructed environment, removing inherited routing,
index/object/config/namespace/executable-path/trace overrides. Replacements,
lazy fetching, global/system config, pagers, prompts and network protocols are
disabled. The resolver invokes no hooks, filters, checkout, fetch, installation
or gates. Repository-local config is still read and externally admitted; the
resolver also rejects unsupported storage settings and includes. Existing
context commands retain their intentional caller/index environment semantics.

Admission does not authenticate policy, approvals, evidence producers or remote
checks, and requires no new App. These documents grant no execution authority.

## Distribution

V1 supports only non-bare standalone checkouts with a real `.git` directory,
SHA-1 objects, detached HEAD at the supplied commit, and complete local
self-contained loose-object/packfile storage. Linked worktrees/`.git` files,
archives, bare/shallow repositories, partial/promisor repositories or packs,
alternates/shared object stores, metadata symlinks and SHA-256 are unsupported.
Missing objects fail without lazy fetch or worktree fallback.

Standalone, detached and nonshallow are bounded v1 choices, not inherent
requirements for immutable-SHA reads or security proofs. They apply to resolver
consumer distributions only, not callers, context invocation, implementation
task worktrees or every future hook/workflow. Referenced symlinks, gitlinks and
trees where blobs are required fail reference validation.

## Revision binding

The physical executing resolver location selects the provider root two
directories above `scripts/contracts/resolve.py`; caller cwd cannot select it.
Detached HEAD equals the supplied commit. Commit/tree, registry, schema and all
resources come from that commit's Git objects. Executing bytes must equal its
resolver blob. Resolver A against provider B fails even with matching schema
versions. Dirty ordinary documents and caller decoys are ignored; dirty resolver
bytes fail. Caller cleanliness, index and documents are not consulted.

Stored `revision_binding: "containing-commit"` avoids an embedded self-SHA.
Successful results replace it with concrete revision/tree. Callers select an
already-existing provider commit externally; final promotion/repinning is separate.

## Stored registry

The [registry](../ai/registry.json) has exactly 31 globally unique entries sorted
by ID: 18 documents, four tasks and nine capabilities. Provider identity is
repository `1380829073`, library `shared-ci`, unit `git-source`. Compatibility
separately routes declared support to `doc.compatibility` and historical evidence
to `doc.evidence`. `release_notes: null` means this slice adds no release-note
route, not that later release obligations are waived.

The [Draft 2020-12 schema](../schemas/ai-registry-v1.schema.json) has root
`#/$defs/stored` and public `#/$defs/result`, `#/$defs/finding` targets. Every
object is closed, every field required, nullable fields present and variants
discriminated. References are document-local; `$schema` is an identifier, not
permission to retrieve anything.

| Task | Exact ordered document selection |
| --- | --- |
| `task.integrate` | `doc.integration`, `doc.registry`, `doc.registry.example`, `doc.context`, `doc.policy`, `doc.quality` |
| `task.change` | `doc.architecture`, `doc.registry`, `doc.context`, `doc.policy`, `doc.quality`, `doc.examples` |
| `task.upgrade` | `doc.compatibility`, `doc.migration` |
| `task.diagnose` | `doc.failure.registry`, `doc.failure.context`, `doc.failure.policy`, `doc.failure.quality`, `doc.recovery` |

Select a document/capability directly for narrower work. Exact paths, anchors,
interfaces and schema/example references live in the machine registry and are
cross-checked against frozen public mappings. `doc.evidence` and `doc.examples`
intentionally identify the same authoritative section, without copying content.

JSON blobs reject BOM, invalid UTF-8, duplicate keys at any depth, NaN/Infinity,
trailing non-whitespace content and escaped lone surrogates. Version is the
integer token `1`, never true, `1.0`, a string or null. Schema mathematical integer
behavior is not this lexical check. Ordering, identities and cross-record/Git
semantics are additional runtime checks, not general JSON Schema validation.

## Resources

Paths are nonempty literal provider-relative POSIX paths: no leading slash,
empty/`.`/`..` segment, backslash, C0/C1 control, `#` or `?`. No trimming,
normalization, decoding, globbing or revision/pathspec interpretation occurs.
Commit trees are walked by literal components. Resources end in regular blobs
of mode `100644` or `100755`; wrappers and the consumer example require `100755`.

Anchors are null or `[a-z0-9]+(?:-[a-z0-9]+)*`. Match ATX headings outside fenced
blocks by lowercasing ASCII letters, removing punctuation other than hyphens,
replacing ASCII-space runs with a hyphen and trimming surrounding spaces/hyphens.
Exactly one match is required; duplicate-heading suffixes are not invented.
Documents return complete strict-UTF-8 text, preserving line endings and final
newline, not just the anchored section.

Pointers are empty or `/` followed by slash-separated nonempty
`[A-Za-z0-9_$.-]+` segments: `^(?:/[A-Za-z0-9_$.-]+)*$`. Required
`/$defs/stored`, `/$defs/result`, `/$defs/finding` therefore work. Lookup is exact
case-sensitive object-key lookup; no escape decoding, array indexing or URL
retrieval. Referenced schema JSON and local references are checked.

Results contain the selected document itself; a task and its listed documents;
or a capability, its contract, recursive capability dependencies and their
contracts. Cycles fail. Entries sort by ID. Resources contain exactly declared
references in that closure, deduplicated by typed reference, sorted by
`(path,type,selector)` (anchor-or-empty, pointer, scope or empty for sources).
Distinct anchors on one file remain separate resources with complete text.

Each resource is `{ref,object,text}`, where `object` is `{blob,mode,sha256}`:
nonzero lowercase 40-hex Git OID, regular mode, lowercase 64-hex SHA-256 of raw
blob bytes. Only document text is nonnull. The result also reports schema,
provider, revision, tree, selected ID and basis marks for fixed registry/schema/
resolver paths. Schemas, source and example bodies are not implicitly returned.

## Capability parity

The nine capabilities are six `cap.context.*` commands (`audit`, `resolve`,
`layers`, `field`, `contexts`, `run`), `cap.policy.evaluate`,
`cap.quality.aggregate`, `cap.contract.resolve`. Each context capability records
both executable wrapper and direct `_context.py COMMAND` forms, not additional
capabilities. Static source/AST checks verify wrapper target/dispatch, parser
handlers, arguments, choices and defaults without importing either module.

Policy `evaluate_policy` has required keyword-only `baseline: dict`,
`candidate: dict`, `approvals: list`, `observation: dict`, returning `dict`.
Quality `aggregate_6dq` has required keyword-only `expectation: dict`,
`evidence: dict`, returning `dict`, depending on `cap.policy.evaluate`.
Static checks cover ordered annotations, absence of defaults/positional/variadic
parameters, and quality's public policy import/call. This is discovery/signature
parity, not executable pure-function integration or a supplied namespace importer.
Private helpers are not public capabilities.

The resolver records `-I -S -B`, required git/revision/entry options, its three
schema targets, existing finding schema and example/test sources. A fixture
reference means source exists, not that it ran. Finding-v1 describes a finding,
not the full policy return envelope. Existing contracts remain authoritative.

## Errors

Precedence: tool availability → distribution → revision binding → registry
transport/version/closed shapes/exact IDs/order → schema availability/definitions/
local references → reference graph/grammar → all resources in resource order →
capability consistency in ID order → selection/closure/output. Unknown selection
cannot hide global breakage. Unsupported integer version precedes unrelated
shape errors. Work is bounded by provider registry/resources, not caller-project
traversal. Schema definition checks are purpose-built, not a general engine.

Findings have exactly `layer: "contracts"`, fixed `path`, `kind`, fixed `detail`,
`red_lines: []`. Detail is the following sentence plus
` Repair: docs/registry-resolution-contract.md#ANCHOR`. Provider kinds use path
`scripts/contracts/resolve.py`; others use `ai/registry.json`.

| Kind | Sentence | Anchor |
| --- | --- | --- |
| `provider_tool_unavailable` | Required admitted tool is unavailable. | `tool-admission` |
| `provider_distribution_unsupported` | Provider distribution is unsupported. | `distribution` |
| `provider_revision_mismatch` | Provider and resolver revision binding failed. | `revision-binding` |
| `registry_invalid` | Stored registry is invalid. | `stored-registry` |
| `registry_schema_unsupported` | Registry schema version is unsupported. | `stored-registry` |
| `contract_missing` | Required committed resource is unavailable. | `resources` |
| `contract_reference_invalid` | Contract reference is invalid. | `resources` |
| `contract_api_drift` | Public capability inventory differs from committed source. | `capability-parity` |
| `contract_entry_unknown` | Requested entry is unknown. | `cli` |

Missing entries/local blobs use `contract_missing`. Unsafe modes/traversal,
invalid text/schema and missing anchors/pointers use `contract_reference_invalid`.
Malformed registry uses `registry_invalid`. Raw Git stderr, exception bodies,
absolute tools, caller content and unvalidated inputs never enter findings.

## Offline consumer example

The [executable example source](../examples/contracts/resolve-from-caller.sh)
accepts exactly this ordered form; it is authored but unexecuted:

```sh
"$ADMITTED_SH" "$PROVIDER_DIR/examples/contracts/resolve-from-caller.sh" \
  --python "$ADMITTED_PYTHON" --git "$ADMITTED_GIT" \
  "$PROVIDER_DIR" "$PROVIDER_REVISION" task.upgrade
```

It validates argument shape/absolute paths and execs supplied Python with
`-I -S -B`, forwarding options and preserving streams/status. It does not
authenticate, discover/install tools, fetch, write pins, change cwd or mutate
callers. Argument errors use stderr/exit 2; success adds no wrapper chatter.

For future separately admitted materialization, confirm producer HEAD equals
the already-existing selected commit, then use a controlled environment:

```sh
"$ADMITTED_GIT" -C "$BUNDLE_SOURCE" bundle create "$BUNDLE_FILE" HEAD
"$ADMITTED_GIT" init --template= --object-format=sha1 "$DISTRIBUTION"
"$ADMITTED_GIT" -C "$DISTRIBUTION" bundle unbundle "$BUNDLE_FILE"
"$ADMITTED_GIT" -C "$DISTRIBUTION" checkout --detach "$PROVIDER_REVISION"
```

Targets are unique run-owned paths. The bundle has no prerequisites; the fresh
repository has no alternates/promisor/shared-store dependency. An independent
observer checks revision/tree, resolver/example bytes, required assets and modes.
Consumption must survive producer-path unavailability. These are planned commands,
not authoring execution. The resolver itself performs none of these writes.

A separate synthetic Git caller contains valid context metadata, `src/example.py`
and same-name ai/docs/scripts decoys. `task.upgrade` returns that task plus
`doc.compatibility` and `doc.migration`, distinct references to the complete
committed integration document, checked against independently measured identities.
The same distribution exercises existing context forms:

```sh
"$ADMITTED_SH" "$DISTRIBUTION/scripts/context/resolve" src/example.py --format json
"$ADMITTED_PYTHON" -I -S -B "$DISTRIBUTION/scripts/context/_context.py" \
  resolve src/example.py --format json
```

Existing wrappers need a run-owned PATH with reviewed `python3`, `git`, `dirname`
mappings, not inherited caller PATH. The journey includes wrong pins, missing
committed resources, dirty documents, mixed resolver bytes and restoration of
a synthetic caller provider/revision tuple. Old/new distributions stay separate.
This is planned local Git-source consumption/reference restoration, not product
rollout, arbitrary copied-script migration, workflow/hook installation or undoing
gate side effects.

## Isolated verification source and admission

Inspect the complete [fixture](../tests/contracts/fixture.py), imports/top-level
code, arguments, writes, environments, subprocess deadlines, abnormal exits and
cleanup before execution. The [isolation entry](../tests/contracts/test_isolation.py)
imports no resolver, collects no behavioral tests and creates no Git fixtures
before preflight. D1 means test isolation, not documentation.

The external launcher owns a unique canonical nonrepository envelope, precreates
`admission.json`, and independently admits tools/source plus sibling sentinels.
Candidate markers do not establish external authority. The record contains:

| Field | Externally supplied value |
| --- | --- |
| `schema`, `envelope`, `uid`, `nonce` | 1; canonical absolute envelope; owner UID; unique 64-hex nonce |
| `runs` | Exact run ID → `isolation`, `behavior` or `schema`; IDs match `[a-z][a-z0-9-]{0,63}` |
| `tools` | Needed python/git/shell/dirname → `{path,sha256}`, admitted canonical executable |
| `sentinels` | Envelope-relative `sentinels/...` file → independently measured SHA-256 |
| `source` | `{root,revision,files}`: admitted producer/C1; complete candidate path → `{mode,sha256}` |
| `validator` | Schema stage only: `{root,version,files}`, external frozen offline dependency closure; file → SHA-256 |

Original-source preservation and independent content/D1 review remain external
preconditions. This record is not a candidate-generated receipt or authentication
mechanism. Paths are private execution inputs, never public registry content.
Fixtures do not repurpose HOME/CODEX_HOME or edit the parent environment.

After independent source inspection and narrow clearance, isolation-only entry:

```sh
"$ADMITTED_PYTHON" -I -S -B "$TASK_SOURCE/tests/contracts/test_isolation.py" \
  --envelope "$D1_ENVELOPE" --run-id "$D1_RUN_ID" \
  --git "$ADMITTED_GIT" --python "$ADMITTED_PYTHON"
```

Also admit `RUN_ID-a`, `RUN_ID-b`, `RUN_ID-abnormal` as isolation run IDs for
simultaneous/abnormal child probes. Unsafe writes, preexisting unowned targets,
marker loss/mismatch and canonical mismatch must refuse. Sentinels stay unchanged;
valid cleanup removes only the exact owned root; abnormal exit retains attributed
recoverable resources. Deadlines stop/reap only owned children/process groups.
Uncertainty retains resources, not forced cleanup. No ports/services are needed.
An independent observer must witness effects; candidate assertions are not D1
acceptance.

Only after D1 acceptance, use a fresh run with
[`test_resolution.py`](../tests/contracts/test_resolution.py), adding `--shell`
and `--dirname` to envelope/run/git/python options. It asserts public resolver,
wrapper/direct behavior and bundle consumption, not existing suites/product tests.
Pure-function parity remains static.

[`test_registry_consistency.py`](../tests/contracts/test_registry_consistency.py)
is separate, adding `--validator-root` and `--validator-version`. Its test-only
bootstrap verifies an external complete manifest/version for a bytecode-free
offline jsonschema dependency root, rejects symlinks/`.pth`/bytecode, and adds
only that root to isolated stdlib paths. Local Draft 2020-12 resources are
admitted; unresolved retrieval fails. No ambient discovery, install, upgrade or
download occurs. This is not a public consumer importer. If no compatible
validator is admitted, schema-engine execution is unavailable, not authoring
blocked or conformance passed.

Keep static data/source checks, D1 observations, behavior, schema-engine,
distribution-consumer and four-metric coverage evidence separate. New tests are
NOT RUN. Historical context/policy and quality results do not transfer. Real
callers, trusted policy/approval provenance, hooks/index/pushed refs, required CI,
release notes, migration/recovery, independent certification, final distribution
and full 6DQ remain required; this candidate neither completes nor waives them.
