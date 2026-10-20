# Changelog

## Unreleased — planned v0.7.0

### Added

- Reusable hourly/manual stuck-PR reporting workflow and caller template, with
  configurable failure-completion/age thresholds, exact-head required-check inspection,
  one comment per head and a reconciled summary issue. Uses only `GITHUB_TOKEN`.
- Offline behavioral and workflow-contract tests in the native verification entry.

### Changed

- Current agent protocol and documentation use GitHub auto-merge for every
  non-Draft PR without human or code-owner approval, preserving required checks
  and AI review.
- Review rules and prompt no longer require an Owner decision or code-owner
  approval for any change. Unverifiable Owner request/approval claims are always
  non-blocking notes; optional verified decisions and all security red lines remain.

### Adoption and publication

This is a prepared version and release note, not a published release. Publication
uses the repository's existing release process; no tag is created by this change.
Consumers pin the final delivered **full commit SHA**, never this planned version
or a floating branch/tag. The published notes must identify that final SHA.

The repository's existing provider pins, selected-protocol snapshots and their
tests remain unchanged. Self-adoption of the new provider is a separate change
after publication. The legacy ruleset planner/template are unchanged; live
settings and ruleset migration remain separate administrator operations. The
existing planner's `--no-code-owner-review` option supports the new policy.
