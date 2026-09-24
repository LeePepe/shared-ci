---
layer: Quality
owns: [scripts/quality/**, tests/quality/**]
depends_on: [Policy]
red_lines: ["Anything other than an explicit pass fails the aggregate."]
---

# Quality

See [docs/architecture.md](../../docs/architecture.md) and the contract docs for behaviour.
