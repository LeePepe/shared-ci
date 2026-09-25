# Caller bootstrap and directory template kit

This is a proposed generation/migration kit, not provider self-adoption, a release
or a consumer rollout. The supported metadata baseline is published commit
`d8fe8e3c68182e3d8435120814bae955ee327372`. Its
[contract](https://github.com/LeePepe/shared-ci/blob/d8fe8e3c68182e3d8435120814bae955ee327372/ai/repo-contract.md#opt-in-metadata-and-directory-audit)
is authoritative for metadata support; read the versioned
[AI usage bundle](https://github.com/LeePepe/shared-ci/blob/d8fe8e3c68182e3d8435120814bae955ee327372/ai/USAGE.md)
as well. Older providers do not acquire metadata support retroactively.

## Generate together

Copy the following from `templates/`, retaining executable bits on both scripts:

| Template | Caller path |
| --- | --- |
| AGENTS.md, CLAUDE.md | same root filenames |
| repo-contract.json, CODEOWNERS, pull_request_template.md | `.github/` |
| ci.yml, review.yml | `.github/workflows/` |
| repository-guide.md, development.md | `docs/` |
| tech-context.root.md | `docs/architecture/tech-context.md` |
| tech-context.leaf.md | each actual layer's `tech-context.md` |
| scripts/verify, githooks/pre-push | `scripts/verify`, `.githooks/pre-push` |

Replace every `<40-char-sha>` with the same supported full lowercase provider
SHA and `@OWNER` with the actual review owner. Choose real repository layer
responsibilities, ownership (including tests), dependencies and gate commands;
the Swift examples are not a mandatory architecture. Preserve an existing
`docs/development.md` and its repository-defined PR units rather than replacing
it mechanically. Keep `.shared-ci/` ignored. Stage the generated files so that
the audit can validate executable bits and tracked regular routes.

The protected repository guide includes the complete shared protocol snapshot
and a review-relevant extract of the development guide. Adapt that extract to
the repository's real PR units and include all additional review policy inline.
The development guide remains the authority for repository development choices;
changes to those choices must update the reviewer extract in the same change.
A tool-free reviewer cannot follow links. Both review callers therefore pass
`rules-file: docs/repository-guide.md`; CODEOWNERS protects this guide and the
development source. Keep the **entire** guide below the selected provider's
24,000-byte input limit and verify rendered prompt contents, not just a link.
When copying protocol text into a caller guide, rebase provider-relative links
to immutable URLs at that same selected SHA. Validate the target document and
fragment in the selected provider; do not silently turn shared-contract links
into missing caller-local documents. Preserve all protocol policy text.

Before switching review routing, put the protected complete guide on the trusted
default branch through its own reviewed prerequisite. `pull_request_target`
reads base configuration: a guide present only in PR head does not fix base
review input. Bootstrap/protection changes remain important Owner-reviewed PRs.
No ruleset, runner or server enforcement is installed by copying these files.

## Bootstrap behavior and compatibility

The script requires Python 3.9+, Git and Bash. With metadata present, the
bootstrap checks a tracked regular metadata envelope, schema integer 1, unique
JSON keys and a full lowercase SHA. Malformed/untracked/symlink metadata fails
without falling back to AGENTS. The pinned provider's audit then checks the
complete guide/dependency/workflow contract before caller gates run.

Without metadata, use `AGENTS.legacy.md` in place of AGENTS.md, retaining the
legacy headings and one full-SHA protocol pointer. The bootstrap supports this
legacy mode; legacy consumers may keep their existing compatible provider.
Do not combine directory-only AGENTS with an old provider or omit metadata.
The tests exercise both modes with the published baseline, not every old SHA.

An absent default `.shared-ci` is initialized and fetched at the exact SHA.
An existing provider path is **never** deleted, reset, fetched into or switched.
It must be a clean checkout at that SHA, with no tracked, untracked or ignored
dirt; a clean linked worktree is supported. Assume-unchanged/skip-worktree
index flags (including sparse layouts) are rejected without changing the index,
because they can conceal modified executable code from Git status. Files, symlink caches (including
broken links), non-repositories, nested subdirectories and wrong/dirty checkouts
fail and are preserved. Parent paths are canonicalized to support platform temp
aliases. Explicit `SHARED_CI` must already exist and satisfy the same checks.
Spaces in provider paths are supported. A failed fresh fetch can leave the new
cache behind; inspect/preserve it and supply a separate clean checkout rather
than expecting destructive repair. No concurrent hostile mutation guarantee is
made for a local caller-controlled cache.

Provider Git subprocesses clear Git's repository-local environment variables,
including inherited hook index/worktree/object settings. The caller's own Git
environment and index remain intact for its audit and gates. Isolated Python
invocation prevents inherited module paths and generated bytecode in the cache.
Explicit empty changed-only CI selection runs no layer gates; missing/uncertain
selection runs all. Fixture selection state must not leak from provider CI.

## Validate, migrate and roll back

1. Record the existing coordinated caller pin/configuration and protection state.
2. Publish/review the trusted guide prerequisite, then migrate metadata, index,
   bootstrap, matching workflow pins, review routing and protection as one purpose.
3. Run audit, `scripts/verify --all`, changed/selected paths, and the actual hook.
   Check malformed metadata, cache preservation and rendered complete reviewer
   input. Keep the same required checks; obtain current-head CI and Owner review.
4. On rollback, restore the **whole recorded compatible caller configuration**:
   old provider pin, metadata presence/absence, AGENTS, bootstrap, guide/review
   routes and CODEOWNERS. Preserve every existing cache; point `SHARED_CI` at a
   clean checkout for the rollback pin. Never reset shared tags or waive checks.

`tests/repo/test_bootstrap.py` generates actual templates and exercises the
published provider locally. Hosted review/model execution, live rulesets and real
consumer adoption remain separate evidence; local test counts prove none of them.
