<!--
PR goals: base = default branch; one purpose; one layer scope where possible;
independently mergeable. Stacked PR? After its base merges, retarget to main and
`git rebase --onto origin/main <old-base-tip>` before merging (squash merges
otherwise make the stacked branch conflict).
-->

## Existing behaviour

<!-- What the code does today that this PR touches, including behaviour that must stay unchanged. -->

## Intent

<!-- What changes and why. Link the task/issue/spec. -->

## Compatibility

<!-- API, data, config and UX compatibility; migrations; how to roll back. Write "no change" if so. -->

## Removed or weakened tests or policy

<!-- Name each affected test file and explain removals/assertion/skip changes for normal AI review; test changes alone need no Owner approval or ledger. Separately identify policy/gate/ruleset changes and their required approvals. Write "none" only when there are none; test-integrity checks the explanation against the diff. -->

## Test evidence

<!-- `scripts/verify` result and the tested SHA (the PR head). A new push invalidates this. -->
- Command:
- Result:
- Tested SHA:
