# Upgrade and rollback

Use [COMPATIBILITY](COMPATIBILITY.md) to compare an old provider pin with a target
pin. A documentation-only addition does not require consumer code changes or
silently upgrade existing consumers.

## Migration directions

| From | To | Required adaptation |
| --- | --- | --- |
| Commit with only docs entry paths | Commit containing this ai bundle | Read the new entries at the target SHA; old docs paths and registry routes remain valid |
| Existing pinned provider | New reviewed full provider SHA | Compare contracts/templates and change all consumer pins and pointers together |
| Caller-local copied scripts | Pinned provider implementation | Inventory local changes first; follow the [source migration procedure](../docs/integration-and-migration.md#migration-and-rollback) rather than assuming parity |
| Legacy CONTEXT layout | Repo-kit tech-context layout | Follow the target [repository contract](repo-contract.md); adopting the layout opts into its repository audit |

No numbered release transition is claimed here. Choose real old/new commit
identities at migration time. Unsupported proposed Context metadata needs its
own published provider and migration evidence, not a speculative configuration.

## Execute one consumer upgrade

1. Record the old provider SHA, consumer baseline, effective required checks,
   commands, caller adapters and configuration. Preserve a recoverable baseline.
2. Compare target contracts, schema semantics, outputs and failure behavior.
   Account for each caller-local override; reject unsupported adaptations.
3. In a dedicated consumer PR update all workflow pins and protocol/dependency
   pointers to one full target SHA, plus necessary adaptations. Preserve
   business facts and required checks. Dependency-pin and gate/policy changes
   retain Owner review under the [agent protocol](agent-protocol.md).
4. Run the consumer verification entry, positive behavior and applicable
   negatives: wrong/mixed pin, missing required artifact, failing selected lane
   and stale candidate evidence. Record provider/consumer SHAs and actual
   findings. Confirm hosted aggregate and required review on that consumer head;
   local synthetic tests do not satisfy the hosted release check.
5. Read back enforcement and document remaining gaps before retiring the old
   route. Each consumer upgrades independently; provider defects return to a
   new provider change rather than a copied local workaround.

## Rollback and irreversible limits

Revert the consumer upgrade as a reviewed change to restore its previous full
pin, compatible configuration, adapters and documentation pointers together.
Re-run verification and required CI on the rollback head. Preserve published
commits/tags; never retarget a release alias to hide a defect. If the previous
provider cannot enforce required semantics, stop and use the
[recovery plan](../docs/disaster-recovery.md) instead of a floating fallback.

This documentation addition performs no data migration. Source/pin rollback
does not undo commands already run, remote settings, lost artifacts or data
side effects; those need a separately authorized recovery plan. Old receipts
and approvals are not fresh evidence for the rollback candidate.
