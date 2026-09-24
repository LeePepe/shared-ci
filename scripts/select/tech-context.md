---
layer: Select
owns: [scripts/select/**, tests/select/**]
depends_on: [Context]
red_lines: ["When in doubt, select a full run: an error, an unmapped path or a non-PR event never narrows the selection."]
---

# Select

Changed-layer CI selection. See [docs/changed-layer-selection.md](../../docs/changed-layer-selection.md).
