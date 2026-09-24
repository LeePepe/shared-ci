---
layer: Review
owns: [scripts/review/**, tests/review/**]
depends_on: [Context]
red_lines: ["Never execute PR head code; codex fails closed; kimi never blocks."]
---

# Review

See [docs/architecture.md](../../docs/architecture.md) and the contract docs for behaviour.
