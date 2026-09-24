---
# Root layer map (repo-kit format). Place at docs/architecture/tech-context.md.
# Every tracked path must resolve to exactly one layer (leaf `owns`) or one
# `support` exclusion. `scripts/context/audit` enforces that plus table drift.
layer: _root
support:
  - patterns: ["*.md", "docs/**", ".github/**", ".githooks/**", "scripts/**", ".gitignore"]
    reason: repository support files; checked by the contract audit, not a layer gate
red_lines:
  - Dependencies point only in the direction listed in the table below.
---

# <Repository> tech context

| Layer | Responsibility | tech-context | depends_on |
|---|---|---|---|
| Core | Pure domain types, no external dependencies | `Packages/Core/tech-context.md` | (none) |
| App | Use cases and wiring | `Packages/App/tech-context.md` | Core |

The `depends_on` column must equal each leaf's frontmatter (audit reports
`layer_table_drift`). External dependencies are described in prose, not in
`depends_on`.
