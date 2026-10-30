# Apple CI architecture

This document is the canonical contract for the six Apple CI/CD optimizations
used by the repository's Apple consumers. The implementation is intentionally
split between the repository's Apple gate, the workflow, and the shared-ci
selector:

- [`scripts/select/apple_shards.py`](../scripts/select/apple_shards.py) discovers
  active XCUITest methods and emits a per-device matrix.
- [`tests/select/test_apple_shards.py`](../tests/select/test_apple_shards.py)
  protects discovery, balancing, skip behavior, and GitHub output shape.
- `build-for-testing` produces the test products once; `test-without-building`
  consumes those products in each dynamic shard.

## 1. Simulator and workspace setup fast-path

The build lane uses `PARALLEL_TESTING=NO` when one worker is responsible for
the build artifact. The destination helper resolves a simulator with
`--no-boot`, so build preparation does not spend time booting a device that
will be prepared by a shard later. `xcodegen` is conditional: a reusable
checkout can set `SKIP_XCODEGEN=1` when the project is already present.

CI reuses Swift package state through `.spm-cache/workspace-state.json` and
fetches `origin/main` before calculating a pull-request diff. A missing or
failed diff must fall back to a safe full Apple plan rather than narrowing the
run.

## 2. In-process XCUITest reuse and hit-target invariant

XCUITests should use a `launchOrReuse` helper for the application under test.
After a launch or reuse, accessibility hit targets are placed and padded before
the test interacts with them; padding must not replace the native control or
make its accessible frame smaller than the visible affordance.

Each test resets state by dismissing modal sheets, browser views, and SERP
surfaces before starting the next scenario. This keeps method-level shards
independent while avoiding a process launch for every test method.

## 3. Xcode test-plan contract

The `.xctestplan` is a versioned interface, not generated test data. Every
`configurations[].id` is a stable UUID, and each target uses a root-relative
`containerPath`. Targets covered by the Swift `Architecture` test suite are
disabled in the UI test plan to avoid duplicate execution.

The supported selection controls are:

```text
-testPlan WebIQSearch
-only-testing-configuration <configuration>
-only-testing:<target-or-method>
-xctestrun <relocated test-run file>
```

The dynamic planner emits `only_test_targets` entries in the form
`AppUITests/ClassName/testMethod`; unit targets remain target-level entries on
shard zero. The plan must not emit an empty shard.

## 4. In-process Prefire trait matrix versus XCUITest consolidation

Fast, deterministic rendering and behavior coverage belongs in the in-process
`Prefire` trait matrix. `DeviceConfig`, `PreviewModel`, and `PrefireSnapshot`
cover `Light`, `Dark`, `AccessibilityLarge`, `iPhone`, and `iPad` combinations
without paying simulator startup cost.

XCUITest remains for system integration and accessibility behavior. Related
scenarios are consolidated into a single method where the setup and teardown
are identical, while opt-in live/smoke methods guarded by
`XCTSkipUnless(ProcessInfo.processInfo.environment[...)` are excluded from the
default dynamic matrix.

## 5. Build once, test many

The required data flow is:

```text
ios-build
  -> plan_apple_shards(...)
  -> ios-shards matrix
  -> ios required-check gate
```

`ios-build` runs `build-for-testing`, packages the resulting `.xctestrun` and
test products, and uploads one short-lived artifact. Each `ios-shards` leg
extracts that artifact and runs `test-without-building` with its device and
`ONLY_TEST_TARGETS` values. The test-run file is relocated after extraction;
the shard must not run `xcodegen` or restore `.spm-cache` merely to execute
already-built products.

The planner balances contiguous UI-method slices per device. Unit targets are
attached to shard zero, and `shard_count_per_device` grows automatically when
the discovered method count crosses a shard boundary. If no Apple target is
affected, it emits `skip_all_apple_tests=1` and an empty matrix.

## 6. Standalone PR CI and main release CD

PR validation is a standalone gate in `ci.yml` on `pull_request`. It does not
receive TestFlight signing secrets. Main-release publication is a separate
`testflight.yml` flow on `push: branches: [main]` inside the protected
`testflight` environment.

Unsigned simulator and compile-only artifacts are not reusable signed Release
`.ipa` inputs: they have different build settings, signing identities,
provisioning, and publication evidence. Keeping the workflows separate also
eliminates duplicate post-merge simulator runs on `main`; the PR gate proves
the change, while the protected CD flow proves the signed delivery.

## Consumer contract

Consumers should begin at [`docs/repository-guide.md`](repository-guide.md),
use [`changed-layer-selection.md`](changed-layer-selection.md) for fail-closed
selection semantics, and use [`automated-release.md`](automated-release.md) for
the standalone release boundary. Pin the delivered shared-ci source by full
SHA; local source presence does not claim hosted merge protection or Apple
signing enablement.
