<!--
PR goals: base = default branch; one purpose in a repository-defined work unit;
independently mergeable. Read the development guide indexed by AGENTS.md.
Stacked PR? After its base merges, retarget to main and
`git rebase --onto origin/main <old-base-tip>` before merging (squash merges
otherwise make the stacked branch conflict).
-->

## Existing behaviour

<!-- What the code does today that this PR touches, including behaviour that must stay unchanged. -->

## Intent

<!-- What changes and why. Name the repository-defined PR unit and link the requirement/spec/task when present. Dev Team work also identifies its Planner task; other sources need no Dev Team task. -->

## Compatibility

<!-- API, data, config and UX compatibility; migrations; how to roll back. Write "no change" if so. -->

## Removed or weakened tests or policy

<!-- List removed/skipped/weakened tests/assertions and policy/gate/ruleset changes with reasons, or "none". When test integrity is enabled, put each affected file on its own line as `path`: reason (JSON-quoted paths also work); keep this section heading unchanged. Approval and review routing follow the pinned agent protocol; ordinary test-code changes do not themselves require Owner approval. -->

## Test evidence

<!-- `scripts/verify` result and the tested SHA (the PR head). A new push invalidates this. -->
- Command:
- Result:
- Tested SHA:
