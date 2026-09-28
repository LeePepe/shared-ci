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

Each layer needs its own verification command and build-enforced dependency
direction. In Swift, default to one layer per SPM package, or per target for
genuinely separate responsibilities; the app shell is its own layer. Non-code
CI, docs/spec, policy/review config and tooling are support areas. Executable
tools under `scripts/` still need ownership and explicit verification; broad
support exclusions must not hide them. Tests belong to the layer they exercise.

Layers serve context routing, CI/test selection and dependency direction, not
PR scope. [PR kinds](../development.md#pr-kinds) and permitted companion changes
follow one goal per PR; layer ownership stays here.
