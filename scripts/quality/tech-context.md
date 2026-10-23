---
layer: Quality
owns: [scripts/quality/**, tests/quality/**]
depends_on: [Policy]
red_lines: ["Anything other than an explicit pass fails the aggregate."]
---

# Quality

Owns the fail-closed Actions gate, PR-range quality checks
([test integrity](../../docs/test-integrity.md) and
[commit identity](../../docs/commit-identity.md)), fail-closed `G2` security
scanning (`scripts/quality/security_scan.py`), cross-target version sync and
live-readback verification (`scripts/quality/release_sync.py`), and pure
[6DQ receipt reconciliation](../../docs/quality-aggregation-contract.md).

See [docs/architecture.md](../../docs/architecture.md) for the surfaces and dependencies.
