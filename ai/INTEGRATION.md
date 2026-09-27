# Integrate a pinned provider

Use this entry for first adoption; use [MIGRATION](MIGRATION.md) for an existing
caller. Check [COMPATIBILITY](COMPATIBILITY.md) before choosing a surface.

## Establish the boundary

1. Select an existing, reviewed provider commit and record its full SHA.
   Obtain code, templates, schemas and this [bundle](USAGE.md) from that commit.
   Verify the source origin and tool identities before execution; a path alone
   is not authentication.
2. Read the consumer's directory and root/leaf contexts. Map its responsibilities
   and verification commands under the [repository contract](repo-contract.md).
   Keep business facts and adapters in the consumer.
3. Choose only the applicable surfaces below. Record provider SHA, consumer
   candidate SHA, trusted policy source and every unresolved adapter separately.

| Surface | Integration source | Boundary |
| --- | --- | --- |
| Reusable CI/review | [Pinning procedure](../README.md#how-a-consumer-pins-it), [CI template](../templates/ci.yml), [review template](../templates/review.yml) | Replace template placeholders; full SHA in every caller reference and protocol/dependency pointer |
| Local context checks | [Context contract](../docs/context-cli-contract.md) | Provider path selects implementation; current working directory selects caller |
| Machine discovery | [Registry admission and distribution](../docs/registry-resolution-contract.md#tool-admission) | Resolver v1 needs its admitted standalone detached distribution, not a linked implementation worktree |
| Policy and quality functions | [Source adapters](../docs/integration-and-migration.md#pure-functions) | No CLI/installer; caller owns reviewed import, decoding and trusted input provenance |

## Local context example

From a caller Git root with tracked repo-kit metadata, set ADMITTED_PYTHON to
the absolute reviewed Python executable and PROVIDER_DIR to the absolute
reviewed checkout at the selected SHA. This exact block is exercised against a
synthetic caller by the [bundle tests](../tests/repo/test_ai_bundle.py), including
a missing-AGENTS failure. It is not evidence of product adoption.

```sh
"$ADMITTED_PYTHON" -I -B "$PROVIDER_DIR/scripts/context/_context.py" audit
```

A clean audit returns 0; findings return 1. Other context/argument errors follow
the [command contract](../docs/context-cli-contract.md#commands-and-outputs).
Audit validates declarations, not arbitrary language imports or PR intent.

## Acceptance before rollout

Run the consumer's existing verification entry and check positive and negative
cases from its own acceptance inventory. Wire local hooks and CI to that same
entry; preserve existing checks. Compare effective remote required checks and
CODEOWNERS with the intended configuration. Settings changes require the
separate approved dry-run/apply/readback process in the
[repository contract](repo-contract.md); local success cannot establish remote
enforcement.

Release verification requires a real caller's aggregate to pass with the
published provider SHA and a negative case to be blocked. Record exact provider
and caller SHAs and hosted run links. Review workflows must keep their existing
trusted-runner and fork restrictions. Do not treat a short-circuited lane as a
tested layer. An integration is incomplete while any required check, review,
adapter or enforcement observation is missing.
