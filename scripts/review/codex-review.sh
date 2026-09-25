#!/usr/bin/env bash
# Deterministic codex review gate, run by .github/workflows/codex-review.yml.
#
# Trust model: the caller checks out the TRUSTED BASE of the PR at ./ and this
# shared-ci revision at $SHARED_CI_DIR. The PR head is fetched as git objects and
# read only as a diff (data). Nothing from the PR head is executed. The fork
# guard lives in the workflow's job-level `if:`, never in this script.
#
#   no blockers                 -> sticky comment, exit 0
#   critical/high blockers      -> sticky comment with findings, exit 1
#   any tool/setup/parse failure -> sticky "unavailable" comment, exit 1 (fail closed)
#
# Env: PR_NUMBER BASE_SHA HEAD_SHA BASE_REPO GH_TOKEN SHARED_CI_DIR
# Optional: CODEX_BIN, CODEX_LAUNCHER (trusted base-tree argv prefix; receives CODEX_BIN and
# the exec arguments and inserts `exec` itself), REVIEW_RULES_FILE, REVIEW_MAX_BYTES,
# REVIEW_MARKER, CODEX_REVIEW_HOME.
set -uo pipefail

: "${PR_NUMBER:?}"; : "${BASE_SHA:?}"; : "${HEAD_SHA:?}"; : "${BASE_REPO:?}"; : "${SHARED_CI_DIR:?}"
REVIEW_DIR="$SHARED_CI_DIR/scripts/review"
MARKER="${REVIEW_MARKER:-<!-- shared-ci-codex-review -->}"
MAX_BYTES="${REVIEW_MAX_BYTES:-200000}"
CODEX_BIN="${CODEX_BIN:-codex}"
export CODEX_HOME="${CODEX_REVIEW_HOME:-$HOME/.codex-review}"

WORK="$(mktemp -d -t codex-review.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# shellcheck source=scripts/review/sticky.sh
. "$REVIEW_DIR/sticky.sh"

fail_closed() {
    local body
    body="$(python3 "$REVIEW_DIR/verdict.py" --tool codex --mode gate --marker "$MARKER" \
        --head "$HEAD_SHA" --unavailable "$1")"
    post_sticky "$MARKER" "$body"
    echo "[codex-review] fail closed: $1" >&2
    exit 1
}

command -v "$CODEX_BIN" >/dev/null 2>&1 || fail_closed "codex CLI is not available on the runner."

if ! git fetch --no-tags --depth=200 origin "$BASE_SHA" "$HEAD_SHA" 2>"$WORK/fetch.err"; then
    fail_closed "Could not fetch the exact PR revisions."
fi
git cat-file -e "$BASE_SHA^{commit}" 2>/dev/null && git cat-file -e "$HEAD_SHA^{commit}" 2>/dev/null \
    || fail_closed "PR revisions are missing after fetch."

# Read the immutable base blob, never mutable worktree or PR-head instructions.
python3 "$REVIEW_DIR/rules_input.py" "$BASE_SHA" "${REVIEW_RULES_FILE:-AGENTS.md}" >"$WORK/rules" \
    || fail_closed "Trusted-base repository rules are missing or invalid."

git diff --no-ext-diff "$BASE_SHA...$HEAD_SHA" >"$WORK/diff" 2>/dev/null \
    || git diff --no-ext-diff "$BASE_SHA..$HEAD_SHA" >"$WORK/diff" \
    || fail_closed "Could not compute the PR diff."
git diff --name-only "$BASE_SHA...$HEAD_SHA" >"$WORK/changed" 2>/dev/null \
    || git diff --name-only "$BASE_SHA..$HEAD_SHA" >"$WORK/changed"

if [ ! -s "$WORK/diff" ]; then
    post_sticky "$MARKER" "$MARKER
## codex review: pass

Reviewed head: \`$HEAD_SHA\`

No committed diff between base and head."
    exit 0
fi

TRUNCATED=""
if [ "$(wc -c <"$WORK/diff")" -gt "$MAX_BYTES" ]; then
    head -c "$MAX_BYTES" "$WORK/diff" >"$WORK/diff.cut" && mv "$WORK/diff.cut" "$WORK/diff"
    TRUNCATED="(diff truncated to $MAX_BYTES bytes; review the rest manually)"
fi

ARCH="$(python3 "$REVIEW_DIR/arch_context.py" <"$WORK/changed" 2>&1 | head -c 24000)"

PROMPT="$(ARCHITECTURE="$ARCH" CHANGED="$(cat "$WORK/changed")" \
    TRUNCATED="$TRUNCATED" DIFF="$(cat "$WORK/diff")" \
    python3 "$REVIEW_DIR/render_prompt.py" "$REVIEW_DIR/review-prompt.md" --rules-file "$WORK/rules")" \
    || fail_closed "Prompt rendering failed."

EXEC_ARGS=(--output-schema "$REVIEW_DIR/verdict.schema.json" -o "$WORK/verdict.json"
    --skip-git-repo-check -c sandbox_mode=read-only -c approval_policy=never "$PROMPT")
if [ -n "${CODEX_LAUNCHER:-}" ]; then
    # Trusted base-tree launcher (e.g. a local provider router). Contract:
    # `LAUNCHER CODEX_BIN <exec args>`; the launcher inserts `exec` itself.
    # shellcheck disable=SC2206 # intentional word split of a trusted launcher prefix
    LAUNCHER=(${CODEX_LAUNCHER})
    "${LAUNCHER[@]}" "$CODEX_BIN" "${EXEC_ARGS[@]}" >/dev/null 2>"$WORK/codex.err"
else
    "$CODEX_BIN" exec "${EXEC_ARGS[@]}" >/dev/null 2>"$WORK/codex.err"
fi
RC=$?
if [ "$RC" -ne 0 ] || [ ! -s "$WORK/verdict.json" ]; then
    tail -c 2000 "$WORK/codex.err" >&2 || true
    fail_closed "codex CLI failed (rc=$RC)."
fi

BODY="$(python3 "$REVIEW_DIR/verdict.py" --tool codex --mode gate --marker "$MARKER" \
    --head "$HEAD_SHA" "$WORK/verdict.json")"
STATUS=$?
post_sticky "$MARKER" "$BODY"
case "$STATUS" in
    0) echo "[codex-review] pass"; exit 0 ;;
    1) echo "[codex-review] blocking findings"; exit 1 ;;
    *) echo "[codex-review] invalid verdict; fail closed"; exit 1 ;;
esac
