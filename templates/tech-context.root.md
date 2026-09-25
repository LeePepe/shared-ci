---
# Root layer map (repo-kit format). Place at docs/architecture/tech-context.md.
# Every tracked path must resolve to exactly one layer (leaf `owns`) or one
# `support` exclusion. `scripts/context/audit` enforces that plus table drift.
layer: _root
support:
  - patterns: ["*.md", "docs/**"]
    reason: documentation; contract audit and documentation review
  - patterns: [".github/**", ".githooks/**", "scripts/verify"]
    reason: CI/review wiring; workflow lint, full verification and protected review
  - patterns: [".gitignore"]
    reason: repository configuration; checked by the contract audit and review
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

Adapt the example layers to stable responsibilities and interfaces, not package
count. Executable tools under `scripts/` need an owner; they are not blanket
support exclusions. Tests belong to the layer they exercise. For code kept in
support paths, explain the boundary and its actual verification explicitly.

PR work units and permitted companion changes are in `docs/development.md`;
they refer to this inventory rather than defining a second layer model.
