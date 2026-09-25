# shared-ci candidate entry

Read this directory from the same full provider commit SHA as the code and
workflows you are considering. Relative links stay within that candidate;
branch/tag names and the version labels below do not select an approved release.

The v0.2.0 selection and v0.2.1 integrity slices are development candidates.
Owner policy approval and release sequencing remain pending. In particular,
strict A (declare assertion changes as well as removed tests/files and added
skips) is implemented; choosing A versus B (test-function/file removals only)
is still Owner-owned. No release or real-consumer adoption evidence is supplied
by these pages.

- Work in a repository: follow the existing pin in its AGENTS.md. This
  candidate's [agent protocol](agent-protocol.md) and
  [repository contract](repo-contract.md) are review material, not authority
  to upgrade that pin.
- Find an interface or diagnose a check: use the [task entry map](../docs/ai-usage.md).
  It routes to the authoritative feature contracts, not another API inventory.
- Evaluate an upgrade: read [compatibility](../docs/integration-and-migration.md#compatibility)
  and the [candidate migration checklist](../docs/integration-and-migration.md#selection-and-integrity-upgrade).

Machine discovery is narrower than this entry page. The unchanged
[registry](registry.json) has no selection/integrity capability or dedicated
contract IDs; see the [exact discovery gap](../docs/integration-and-migration.md#selection-and-integrity-discovery-gap).
Following a Markdown link is not evidence that the registry resolves that API.
