# Repository guide

shared-ci supplies versioned repository contracts, context resolution, quality
gates and reusable CI/review workflows. Read the [layer map](architecture/tech-context.md),
then each affected layer's leaf context and feature contract before editing.
The [task map](ai-usage.md) routes interface-specific work.

## Protocol

The provider pin is the `shared_ci` field in
[repository metadata](../.github/repo-contract.json). Read `ai/agent-protocol.md`
at that exact provider revision; the [local protocol](../ai/agent-protocol.md)
is the candidate contract being developed, not a published upgrade.

Dogfood uses an earlier provider revision: change workflow pins and metadata
together only after that revision exists remotely and the pin upgrade is reviewed.
The versioned protocol link in AGENTS is a compatibility route for the earlier
audit, not a second machine authority.

## Verify

```sh
git config core.hooksPath .githooks
scripts/verify --all
```

The hook and CI call this verification entry. It runs the repository's configured
self-tests, syntax checks, contract audit and workflow-lint. Registry fixtures
have separate admission requirements in their contract; this entry is not
proof that those fixtures, a consumer rollout or full 6DQ ran.

## Required checks

- `quality / aggregate`

The effective repository ruleset is the enforcement source. Codex/Kimi review
currently needs a trusted runner; a skipped or queued review is not approval.
This repository's required list does not claim the broader rollout is finished.

## Red lines

- Engines stay stdlib-only Python 3.9+, Git and POSIX shell.
- Anything except an explicit pass fails aggregate; unreadable input fails closed.
- Privileged review never executes PR head code.
- Keep credentials, private identity configuration and local paths out of Git.

Owner-approved policy: editing/deleting tests, assertions and skip conditions
does not itself require Owner approval. Explain detected changes in the PR and
retain ordinary AI review and any applicable Plan-Review. This supersedes the
test-approval clause in the earlier dogfood protocol. CI, gates, schemas,
rulesets, dependency pins and other protected surfaces keep their separate
Owner-review requirements. AGENTS is only the conditional document index.

## Dependencies

[Repository metadata](../.github/repo-contract.json) is the single machine source
for the provider pin and versioned shared-library declarations. CI uses the same
pin; the audit checks parity. Library contracts are read at the declared version.

## Delivery

One task owns one branch/worktree and a focused PR using the repository template.
Gate, lint, schema, contract and workflow changes require protected-path review.
Evidence and independent review bind to the current head; fresh pushes require
fresh checks. Enable auto-merge and leave the server's review/check gates intact.
