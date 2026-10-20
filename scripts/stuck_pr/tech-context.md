---
layer: StuckPR
owns: [scripts/stuck_pr/**, tests/stuck_pr/**]
depends_on: []
red_lines: ["Report only; never repair, rerun, approve or merge.", "Never execute PR code or interpolate PR text into commands."]
---

# Stuck PR reporting

Stdlib-only GitHub API client and report reconciliation. The reusable workflow
checks out only its own provider revision. See [the contract](../../docs/stuck-pr-bot.md).
