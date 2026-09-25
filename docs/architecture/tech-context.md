---
layer: _root
support:
  - patterns: ["*.md", ".gitignore", "docs/**", "ai/**", "examples/**", "templates/**", ".github/**", ".githooks/**", "scripts/verify"]
    reason: contracts, documentation, templates and CI wiring; verified by scripts/verify and the contract audit
red_lines:
  - Engines are stdlib-only Python 3.9+, Git and POSIX shell; no third-party packages.
  - Review scripts never execute PR head code; the PR diff is data.
  - Gate, lint, schema and contract changes are important PRs (Owner review).
---

# shared-ci tech context

| Layer | Responsibility | tech-context | depends_on |
|---|---|---|---|
| Context | Layer-map resolver, contract audit, runner | `scripts/context/tech-context.md` | (none) |
| Lint | workflow-lint engine | `scripts/lint/tech-context.md` | Context |
| Quality | Fail-closed aggregate gate and 6DQ reconciliation | `scripts/quality/tech-context.md` | Policy |
| Select | Changed-layer CI selection (diff → layers + dependents, fail-closed full run) | `scripts/select/tech-context.md` | Context |
| Policy | Policy eligibility evaluator | `scripts/policy/tech-context.md` | (none) |
| Review | codex/kimi review scripts and prompt | `scripts/review/tech-context.md` | Context |
| Registry | Committed registry resolver | `scripts/contracts/tech-context.md` | (none) |
| Schemas | JSON schemas incl. repository contract parameters | `schemas/tech-context.md` | (none) |
| Ruleset | Ruleset-as-code planner and applier | `scripts/ruleset/tech-context.md` | (none) |

`Quality` reads `schemas/repo-contract-v1.json` as data (no code dependency).
Tests live under `tests/<area>/` and belong to the layer they exercise.
