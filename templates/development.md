# Development guide

<!-- Place at docs/development.md or adapt an existing guide. Replace example
units with this repository's real paths, commands and review pointers. -->

## Architecture

[The layer map](architecture/tech-context.md) owns layer IDs and dependencies.
Each referenced leaf owns its implementation/test paths, responsibility,
interfaces and verification commands. Read those sources for the change at hand.
The pinned shared protocol/contract reached through AGENTS defines the common
development rules; this guide records the repository-specific choices.

## PR work units

| Unit | Path source | Permitted companion changes | Verification / review |
| --- | --- | --- | --- |
| Core | Core leaf `owns` | Required behaviour tests and API documentation | Core gates; repository architecture/code review |
| App | App leaf `owns` | Required behaviour tests and feature documentation | App gates and affected dependents; code review |
| CI | Repository workflow/hook/verify entry points | Tests and docs of that wiring change | Workflow lint and full verification; protected-path review |
| Docs / spec | One documentation topic or requirement/spec | Its diagrams and examples | Documentation checks/review; no unrelated implementation |
| Review / policy | Repository's actual policy and reviewer-configuration paths | Policy regression tests and usage docs | Policy checks and existing protected-path review |

Each PR serves one purpose within a unit. Refer to layer ownership instead of
copying its glob lists here. Specify any additional companion paths precisely;
sharing a unit is not permission to bundle independent requirements. For a
cross-layer feature, document the interface and dependency-ordered PRs first.

## Verification and review sources

Use the repository's executable verify entry from both local hooks and CI:

```sh
git config core.hooksPath .githooks
scripts/verify
scripts/verify --all
```

Point to the repository's verify entry, CI configuration and review policy /
CODEOWNERS. Record the command/evidence and `enforced`, `manual`, `planned` or
`N/A` status for actual checks; do not present this example table as enforcement.
PR authors use these conventions regardless of workflow. PRM follows existing
CI/review outcomes without adding a separate size or scope review.
