# Versioned AI documentation

Read this bundle from the same full 40-character provider commit as the engines,
schemas, templates and workflows you consume. Its version is the containing
commit, not a separate documentation version or a schema number. A branch name
or human-readable release tag is not a shared-ci consumption pin.

## Choose an entry

| Task | Entry | Completion evidence |
| --- | --- | --- |
| First integration | [INTEGRATION](INTEGRATION.md) | Provider/consumer SHAs, actual caller commands, local and hosted results recorded separately |
| Check supported interfaces | [COMPATIBILITY](COMPATIBILITY.md) | Each caller assumption compared with the target commit's contract |
| Upgrade or roll back | [MIGRATION](MIGRATION.md) | Old/new pins, adaptations, negative checks and a compatible rollback target |
| Change or diagnose an API | [API task map](../docs/ai-usage.md) | Exact interface, observed finding/status and its contract |
| Develop in a consumer | [Agent protocol](agent-protocol.md), [repository contract](repo-contract.md) | Repository-defined PR unit, verification and required review at the tested SHA |

The repository owns layer responsibilities, allowed dependencies and PR units.
AGENTS is the directory to those sources. The protocol applies to both Dev Team
and other agents; it defines their different task entry paths without creating
role-specific architecture rules. Ordinary test corrections need reasons,
automated checks and AI review; gate/policy changes and pins retain required
Owner review.

## Discovery and authority

The [registry](registry.json) retains its existing document and task IDs.
Its documentation routes still select the established files under docs; their
links lead here without changing the frozen registry interface. Direct users may
read these four ai paths at the selected commit. Read the
[registry contract](../docs/registry-resolution-contract.md) before executing its
resolver: discovery is not permission to install, fetch, run caller gates or
change settings.

This bundle documents source interfaces. Its existence proves neither a release
nor a consumer rollout. Release acceptance still needs an independently reviewed
provider change, a real caller using the published full SHA, a passing aggregate
and a blocked negative case. Release notes must bind those results to the provider
and caller revisions. Local documentation tests are not that evidence.
