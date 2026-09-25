<!--
PR goals: base = default branch; independently mergeable.
Stacked PR? After its base merges, retarget to main and
`git rebase --onto origin/main <old-base-tip>` before merging (squash merges
otherwise make the stacked branch conflict).
-->

## Existing behaviour

<!-- What the code does today that this PR touches, including behaviour that must stay unchanged. -->

## Intent

<!-- What changes and why. Link the task/issue/spec; for Dev Team work, identify the Planner task. No additional scope declaration is required for other sources. -->

## Compatibility

<!-- API, data, config and UX compatibility; migrations; how to roll back. Write "no change" if so. -->

## Removed or weakened tests or policy

<!-- List removed/skipped/weakened tests/assertions and policy/gate/ruleset changes with reasons, or "none". Approval and review routing follow the pinned agent protocol; ordinary test-code changes do not themselves require Owner approval. -->

## Test evidence

<!-- `scripts/verify` result and the tested SHA (the PR head). A new push invalidates this. -->
- Command:
- Result:
- Tested SHA:
