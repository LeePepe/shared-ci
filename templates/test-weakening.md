# Declared test weakening

Copy to `.github/test-weakening.md`. The `quality / test-integrity` check
requires one added line per test file whose assertions or tests a PR
removes, skips or deletes. The Owner approves it through CODEOWNERS
(`/.github/`). Earlier lines never declare a later loss. Keep them as the
history of every approved weakening.

Format: `- <test file path>: <reason, link> (approved: @<owner>)`

