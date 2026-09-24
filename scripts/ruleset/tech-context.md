---
layer: Ruleset
owns: [scripts/ruleset/**, tests/ruleset/**]
depends_on: []
red_lines: ["Dry run by default; --apply only after Owner approval, then read back.", "Preserve existing required checks unless explicitly mapped."]
---

# Ruleset

Plans and applies the default-branch ruleset from `templates/ruleset.json`.
