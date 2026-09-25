# Minimum repository contract

The eight checks remain report schema v1. New adopters use an index-only
AGENTS with [repository metadata](../schemas/repo-metadata-v1.json).
Existing consumers without metadata retain the v1 AGENTS/pin checks at this
provider revision; adopting the new layout is an explicit migration, not a
silent reinterpretation of a pinned old contract.

The [report schema and audit parameters](../schemas/repo-contract-v1.json)
and `scripts/context/_contract.py` come from the same pinned provider.
The contract lane runs the same audit as local verification.

| Item | Authoritative surface | Mechanical check |
| --- | --- | --- |
| 1 `agents` | AGENTS is a document index: headings and conditional Markdown links only. Rules, commands, bootstrap and dependency details live in their linked sources. | At most 150 lines; link-only content, readable route targets and a link to the declared guide; metadata shape and pin/workflow parity. Semantic quality of the routing still needs review. |
| 2 `agent_files` | CLAUDE/GEMINI/copilot/cursor instructions defer to AGENTS and contain only brief tool-specific notes. | Reference to AGENTS, line limit, no duplicate provider pins or required checks from the guide. |
| 3 `ci` | Caller workflows use one full provider SHA. Review callers read the trusted-base guide, not the index as if it contained all rules. | One SHA across uses; quality job is named `quality`; review `rules-file` equals metadata `guide`. Workflow-lint retains trust/fork checks. |
| 4 `verify` | Executable `scripts/verify` is shared by hook and CI; layer commands live in leaf contexts. | Tracked executable entry, executable hook invocation and CI invocation. Bootstrap reads metadata, with legacy AGENTS fallback only when metadata is absent. |
| 5 `ruleset` | Rulesets and CODEOWNERS protect important surfaces. The guide carries repository policy and therefore remains protected after moving it out of AGENTS. | CODEOWNERS covers `/.github/`, `/AGENTS.md` and the exact `/<guide>` path for metadata callers. Live rules still require separate readback. |
| 6 `pr_template` | The repository template records behavior, intent, compatibility, test/policy changes and current-head verification. | Required nonempty sections and tested SHA; test losses are cross-checked with the explanation, not Owner approval. |
| 7 `dependencies` | Metadata declares exact shared-library versions and same-version `ai/` links. | Exact metadata versions, versioned links and supported lockfile parity. The provider has one field, `shared_ci`, not a duplicate dependency entry. |
| 8 `identity` | Credentials, private identity configuration and local home paths stay outside Git. | Existing tracked-text forbidden-pattern checks; tool attribution remains allowed. |

## Metadata and migration

Copy [metadata](../templates/repo-contract.json) to
`.github/repo-contract.json`, [the guide](../templates/repository-guide.md) to
`docs/repository-guide.md`, and use the [index](../templates/AGENTS.md).

```json
{
  "schema": 1,
  "guide": "docs/repository-guide.md",
  "shared_ci": "<full-40-character-provider-SHA>",
  "dependencies": {
    "shared-telemetry": {
      "version": "1.2.3",
      "ai": "https://example.invalid/shared-telemetry/1.2.3/ai/"
    }
  }
}
```

The example is a shape, not a valid pin or an executed integration. The guide
is a tracked, readable repository-relative file and contains Protocol, Verify,
Required checks, Red lines and Delivery sections. Dependency metadata, layer
commands and repository rules each have one source; the guide links rather than
copying them.

Update workflow pins, metadata, verification bootstrap and review
`rules-file` together. Protect the guide in CODEOWNERS and preserve existing
required checks. A versioned protocol link may remain in the index as a
compatibility route; its SHA must match metadata. It is not the machine pin
authority. Invalid metadata fails closed instead of falling back to legacy
AGENTS. Old consumers without metadata continue through the unchanged legacy
sections/pointer/dependency checks; no consumer pin is upgraded automatically.

Run the current provider audit and local verification before proposing a pin
upgrade. For shared-ci dogfood, also check the earlier pinned audit: the index
template keeps the old headings and versioned protocol route for that purpose.
A different consumer with lockfile declarations must migrate atomically to the
new provider; old gates cannot interpret metadata that did not exist in their
version.

## Test integrity

The default-on integrity lane reports assertion/test removals, added skip
markers and deleted test files across the whole PR. Each affected file must be
named and explained in the PR section `Removed or weakened tests or policy`;
a contradictory `none` fails. See the [detector contract](../docs/test-integrity.md).

Test-code edits or deletion do not themselves require Owner approval, a
ledger, approver spelling or CODEOWNERS coverage. Automatic evidence and
ordinary AI review remain. Applicable Plan-Review is not exempted. A PR that
also changes protected CI/gate/policy remains subject to that separate review.

## Selection, enforcement and exceptions

[Changed-layer selection](../docs/changed-layer-selection.md) is optional.
Required checks always report; short-circuiting is not execution evidence.
Metadata lives under `.github/`, so changes select the full validation path.

Ruleset planning/apply/readback remains the
[existing Owner-approved workflow](../templates/ruleset.json). Repository
exceptions belong in the protected guide, not in AGENTS. This contract does
not grant self-service permission to change settings, gates or protected policy.
