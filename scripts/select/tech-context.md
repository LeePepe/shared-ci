---
layer: Select
owns: [scripts/select/**, tests/select/**]
depends_on: [Context]
red_lines: ["When in doubt, select a full run: an error, an unmapped path or a non-PR event never narrows the selection."]
---

# Select

Changed-layer CI selection and deterministic Apple simulator shard planning.
See [docs/changed-layer-selection.md](../../docs/changed-layer-selection.md)
and [the Apple CI architecture](../../docs/apple-ci-architecture.md).

`apple_shards.py` is a stdlib-only Python 3.9+ selector. Its
`test_apple_shards.py` suite is an isolated regression gate, and the resolver
test invokes that suite so a consumer cannot silently drop the shard contract.
