# Trusted repository rules input

The Codex and Kimi review wrappers read the selected rules file from the exact
`BASE_SHA` Git commit, not the checkout, index, PR head or linked documents.
`rules-file` / `REVIEW_RULES_FILE` selects a repository-root-relative path;
omitted or empty selects legacy `AGENTS.md`. An invalid explicit path never
falls back to AGENTS. The file must already exist in the trusted base before
a consumer switches its review caller to that path.

The selected base tree entry must be a regular file (`100644` or `100755`).
Symlinks, directories, gitlinks, missing/untracked files, absolute paths,
traversal and noncanonical path components are rejected. Spaces and Git glob
characters in filenames are literal. Backslashes and control characters in
paths are unsupported. `BASE_SHA` must be a full lowercase commit SHA; local
Git replacement refs cannot substitute another object for it.

Rules must contain nonempty UTF-8 text, with no binary control characters
(other than tab, CR and LF), and be at most **24,000 bytes**. Oversized policy
is rejected, never truncated. Both wrappers preserve the complete selected
text, including its ending newlines, through the required `REPO_RULES` prompt
placeholder. Placeholder-looking text inside policy or diff data is not
recursively substituted.

Invalid rules prevent a model invocation, including when the PR diff is empty.
Codex reports unavailable and fails closed; Kimi reports unavailable but stays
advisory (exit zero). Legacy default selection is preserved, not legacy silent
acceptance of missing or invalid AGENTS. No required-check names or fork trust
boundaries change.

## Directory-mode adoption

AGENTS may be only an index. A tool-free reviewer cannot follow its links:
select a complete protected review guide containing the applicable repository
policy, not merely pointers to protocol/development documents. Keep that guide
within the byte limit and verify its rendered policy sentinels. Protect its
source with effective CODEOWNERS and the repository's actual server rules.
Reading a complete file does not prove policy completeness or effective server
protection; these still need content review and independent readback.

Establish the guide on the trusted base before changing the consumer review
route. Upgrade to a reviewed published provider revision deliberately; an old
provider pin does not gain this validation retroactively. Rollback restores the
recorded compatible caller/provider configuration, never rewrites a provider
revision or disables required gates. This source change does not migrate caller
pins, install runners or change live settings.

The diff-size budget and architecture-facts reader are unchanged. This feature
only hardens selected repository rules; it does not certify other context as
complete or execute any PR-head source. Tests use real local Git base/head
objects and stub model/GH commands, not hosted or product-adoption evidence.
