---
layer: Lint
owns: [scripts/lint/**, tests/lint/**]
depends_on: [Context]
red_lines: ["Unparseable workflows fail closed; never skip."]
---

# Lint

See [docs/architecture.md](../../docs/architecture.md) and the contract docs for behaviour.
