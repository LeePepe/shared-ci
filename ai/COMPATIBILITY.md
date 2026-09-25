# Compatibility of the selected commit

The containing full SHA versions this [bundle](USAGE.md). Schema integers and
human-readable tags are separate identifiers. Match caller assumptions against
the code and contracts at that SHA rather than inferring support from a newer
branch, proposal or matching schema number.

## Declared interfaces

| Surface | Supported shape and source of truth |
| --- | --- |
| Runtime | Python 3.9+ stdlib, Git and POSIX shell for the engines; reusable workflows have their own runner/tool prerequisites |
| Context | Six commands in the [CLI contract](../docs/context-cli-contract.md#commands-and-outputs); legacy recursive CONTEXT and repo-kit tech-context layouts |
| Repository contract | [Eight items and development contract](repo-contract.md); repo-kit audit is opt-in by layout, legacy audit remains compatible |
| CI selection | [Changed-layer selection](../docs/changed-layer-selection.md); opt-in with fail-closed full-run fallback |
| Policy / quality | [Policy](../docs/policy-validation-contract.md) and [quality](../docs/quality-aggregation-contract.md) native-data functions; not package or command-line APIs |
| Registry | [Version 1 profile](../docs/registry-resolution-contract.md#distribution); complete standalone detached nonshallow SHA-1 distribution only |

Linked task worktrees remain supported for development and Context invocation;
the registry distribution restriction does not apply to every shared-ci command.
Unknown or unparseable gate results are not passes.

The [existing compatibility/evidence table](../docs/integration-and-migration.md#compatibility)
distinguishes declared support from bounded synthetic execution. Registry
isolation, behavior and schema fixtures have separate admission prerequisites;
ordinary verify does not run them. Their source presence is not a successful
consumer test or a supported platform matrix.

## Documentation compatibility

These four ai entry paths are additive. Existing docs paths, anchors, registry
IDs and CLI behavior remain unchanged. A provider commit predating this bundle
cannot supply these files: use its existing docs and upgrade explicitly.

This slice does not introduce a new Context metadata file, a directory-only
audit mode, a package installer or a new release tag. Read the selected
[contract schema](../schemas/repo-contract-v1.json) and
[templates](../templates/) for what that provider actually accepts. Proposed
metadata and unpublished checker changes are not supported interfaces.

Follow [MIGRATION](MIGRATION.md) when a caller assumption differs. Keep evidence
of local behavior, hosted CI, review and effective server protection separate;
none is inferred solely from the declarations above.
