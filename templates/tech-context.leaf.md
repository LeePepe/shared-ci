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

## Responsibility and interfaces

Describe this layer's stable responsibility, public interfaces, data flow and
excluded concerns. Adapt the example paths/commands to the repository; include
tests in `owns` even when they live outside the implementation directory.

## Verification

The declared gates and repository import-boundary checks verify this layer.
List any missing checks as gaps; a dependency declaration alone does not prove
imports obey it. Keep these facts here, not in AGENTS or Planner instructions.
