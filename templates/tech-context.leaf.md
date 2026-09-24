---
# Leaf layer context (repo-kit format). Place in the layer directory and list
# it in the root table. `owns` globs are repository-root-relative.
layer: Core
owns: [Packages/Core/**]
depends_on: []
gate:
  build: swift build --package-path Packages/Core
  test: swift test --package-path Packages/Core
red_lines:
  - No imports of other local layers or UI/platform frameworks.
---

# Core

Responsibility, data flow and constraints of this layer. Keep facts here, not
in AGENTS.md. `scripts/context/run Core --gate test` runs a gate.
