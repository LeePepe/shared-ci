# Design contract

Use this document as `docs/design-contract.md` in a UI repository. Replace
the examples with the project's verified design-system facts before enabling
the gate.

## Design system & version

- Upstream design system package: `<package name>`
- Exact version or revision: `<semver or commit SHA>`
- Supported platforms: `<iOS / macOS / web / other>`
- Required appearance modes: `light` and `dark`
- Theme selection is explicit at every view boundary; there is no implicit
  default theme.

## Semantic token profile

Map product roles to semantic tokens supplied by the design system. Business
views must consume these tokens and must not hard-code raw color values.

| Role | Semantic token | Light meaning | Dark meaning |
| --- | --- | --- | --- |
| Brand primary | `<token>` | `<description>` | `<description>` |
| Surface | `<token>` | `<description>` | `<description>` |
| Text primary | `<token>` | `<description>` | `<description>` |
| Text secondary | `<token>` | `<description>` | `<description>` |

## Required view states

Every required page and major component covers all four states:

- `populated`: content is available and rendered with normal interactions.
- `empty`: the valid no-content experience is explicit and actionable.
- `loading`: progress and disabled/intermediate interactions are defined.
- `error`: failure messaging, recovery, and retry behaviour are defined.

## Redlines & CI gate

- Do not add裸色值: no raw Hex, RGB, or RGBA color literals in UI views.
- Do not create private duplicates of shared foundational components.
- Keep token definitions, generated sources, and approved legacy exceptions
  outside the business-view scan or annotate a narrow exception with
  `design-contract-allow: <reason>`.
- Run the static gate from the repository root:

  ```sh
  python3 .shared-ci/scripts/context/design_contract.py \
    --root . --ui-path <dir>
  ```

The gate must pass before a UI change is accepted.

For rendered UI checks, keep PNG screenshots under the repository root and
optionally require all `populated`, `empty`, `loading`, and `error` states in
both `light` and `dark` appearances:

```sh
python3 .shared-ci/scripts/context/design_contract.py \
  --root . --screenshot-dir artifacts/screenshots \
  --require-state-matrix
```

Jev `Noul + Box` checks are opt-in. Use `--jev-mode advisory` to report
findings without failing the gate, or `--jev-mode gate` to fail closed when
the service is unavailable or a visual defect is detected.
`--jev-threshold` defaults to `0.65` and must be a finite probability in
the inclusive range `[0, 1]`; invalid values are rejected before scanning.
