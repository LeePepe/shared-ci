# Changelog

## [v0.7.1](https://github.com/LeePepe/shared-ci/releases/tag/v0.7.1) — 2026-10-20

Published source: `88c09b3f68ceea82a4ca979c689e3dc50266ee10`.

### Changed

- Shared-ci self-adopts the published v0.7.0 provider at
  `0dc389c476e96389322b82b9b95504f5118f82ab` in CI/review callers, protocol route,
  metadata and the active guide snapshot ([#45](https://github.com/LeePepe/shared-ci/pull/45)).
- The ruleset template and planner default to zero approving reviews and no
  code-owner review ([#46](https://github.com/LeePepe/shared-ci/pull/46)).
  `--no-code-owner-review` remains accepted as a compatibility no-op. Existing
  required checks, deletion/non-fast-forward protection, bypass behavior and
  dry-run-by-default behavior remain intact.
- Added ruleset regressions for default creation/update, the template, legacy
  CLI compatibility and mocked apply dry runs; updated the matching contract
  and wrapper documentation.

### Verification and adoption

Native verification passed all 807 tests at the published commit. This source
release applies no live ruleset or repository-setting changes. Consumers adopt
it separately using the full SHA; at publication, shared-ci's own callers still
pin v0.7.0. Publication does not establish v0.7.1 adoption or live bot acceptance.

## [v0.7.0](https://github.com/LeePepe/shared-ci/releases/tag/v0.7.0) — 2026-10-20

Published source: `0dc389c476e96389322b82b9b95504f5118f82ab`
([#44](https://github.com/LeePepe/shared-ci/pull/44)).

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

### Fixed

- Isolate subprocess Git calls in Context reachability test fixtures from
  inherited `GIT_*` variables so normal pre-push verification reads the fixture
  repository. Assertions and the hook remain intact.
- Repair the repository-contract link to agent-protocol section 6.

### Verification and adoption

Native verification passed all 804 tests at the published commit. Existing
provider pins, selected-protocol snapshots and their tests were unchanged;
self-adoption and consumer upgrades remained separate work. The legacy ruleset
planner/template were unchanged; live settings and ruleset migration remained
separate administrator operations. The existing `--no-code-owner-review` option
supported the new policy. Publication does not establish caller adoption or live
bot acceptance.
