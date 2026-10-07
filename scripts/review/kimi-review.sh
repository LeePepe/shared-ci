#!/usr/bin/env bash
# Advisory kimi review, run by .github/workflows/kimi-review.yml. Never fails:
# findings and unavailability are posted as a sticky comment; exit is always 0.
# Same trust model as codex-review.sh: trusted base checkout, PR head read as diff only.
#
# Env: PR_NUMBER BASE_SHA HEAD_SHA BASE_REPO GH_TOKEN SHARED_CI_DIR
# Optional: KIMI_BIN, KIMI_MODEL, REVIEW_RULES_FILE, REVIEW_MAX_BYTES, REVIEW_MARKER.
set -uo pipefail

REVIEW_DIR="${SHARED_CI_DIR:-.}/scripts/review"
MARKER="${REVIEW_MARKER:-<!-- shared-ci-kimi-review -->}"
MAX_BYTES="${REVIEW_MAX_BYTES:-80000}"
KIMI_BIN="${KIMI_BIN:-kimi}"
KIMI_MODEL="${KIMI_MODEL:-kimi-code/k3}"

# Exit 0 is advisory, not proof of model completion. Only a validated model
# verdict can enable the workflow's final review check; direct callers need no output file.
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "completed=false" >> "$GITHUB_OUTPUT"
fi

advisory_unavailable() {
    local body="${2:-}"
    # Report before attempting publication: missing env/auth must not hide this conclusion.
    # Escape workflow-command data; keep the original sanitized reason elsewhere.
    printf '::warning::kimi review unavailable: %s\n' "${1//%/%25}"
    if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
        printf 'kimi review unavailable: %s\n' "$1" >> "$GITHUB_STEP_SUMMARY"
    fi
    if [ -n "${PR_NUMBER:-}" ] && [ -n "${BASE_REPO:-}" ] && [ -n "${SHARED_CI_DIR:-}" ]; then
        if [ -n "$body" ] || body="$(python3 -B "$REVIEW_DIR/verdict.py" --tool kimi --mode advisory --marker "$MARKER" \
            --head "${HEAD_SHA:-unknown}" --unavailable "$1")"; then
            # shellcheck source=scripts/review/sticky.sh
            . "$REVIEW_DIR/sticky.sh" && post_sticky "$MARKER" "$body" || true
        fi
    fi
    echo "[kimi-review] advisory unavailable: $1"
    exit 0
}

for name in PR_NUMBER BASE_SHA HEAD_SHA BASE_REPO SHARED_CI_DIR; do
    [ -n "${!name:-}" ] || advisory_unavailable "Missing required environment: $name."
done

WORK="$(mktemp -d -t kimi-review.XXXXXX)" || advisory_unavailable "Could not create review workspace."
trap 'rm -rf "$WORK"' EXIT

# shellcheck source=scripts/review/sticky.sh
. "$REVIEW_DIR/sticky.sh" || advisory_unavailable "Review comment helper is unavailable."

command -v "$KIMI_BIN" >/dev/null 2>&1 || advisory_unavailable "kimi CLI is not installed on the runner."
git fetch --no-tags --depth=200 origin "$BASE_SHA" "$HEAD_SHA" >/dev/null 2>&1 \
    || advisory_unavailable "Could not fetch the exact PR revisions."
# Read the immutable base blob, never mutable worktree or PR-head instructions.
python3 -B "$REVIEW_DIR/rules_input.py" "$BASE_SHA" "${REVIEW_RULES_FILE:-AGENTS.md}" >"$WORK/rules" \
    || advisory_unavailable "Trusted-base repository rules are missing or invalid."

PROMPT_ARGS=(--rules-file "$WORK/rules")
if python3 -I -B "$REVIEW_DIR/pr_text.py" >"$WORK/pr"; then
    PROMPT_ARGS+=(--pr-file "$WORK/pr")
fi

git diff --no-ext-diff --find-renames --unified=40 "$BASE_SHA...$HEAD_SHA" >"$WORK/diff" 2>/dev/null \
    || advisory_unavailable "Could not compute the PR diff."
git diff --name-only "$BASE_SHA...$HEAD_SHA" >"$WORK/changed" 2>/dev/null || true
[ -s "$WORK/changed" ] || { post_sticky "$MARKER" "$MARKER
## kimi advisory review: pass

No committed diff." || true; exit 0; }

TRUNCATED=""
if [ "$(wc -c <"$WORK/diff")" -gt "$MAX_BYTES" ]; then
    head -c "$MAX_BYTES" "$WORK/diff" >"$WORK/diff.cut" && mv "$WORK/diff.cut" "$WORK/diff"
    TRUNCATED="(diff truncated to $MAX_BYTES bytes)"
fi
# Review must leave a clean provider cache reusable by caller verification.
ARCH="$(python3 -B "$REVIEW_DIR/arch_context.py" <"$WORK/changed" 2>&1 | head -c 24000)"
PROMPT="$(ARCHITECTURE="$ARCH" CHANGED="$(cat "$WORK/changed")" \
    TRUNCATED="$TRUNCATED" DIFF="$(cat "$WORK/diff")" \
    python3 -B "$REVIEW_DIR/render_prompt.py" "$REVIEW_DIR/review-prompt.md" \
        "${PROMPT_ARGS[@]}")" \
    || advisory_unavailable "Prompt rendering failed."
PROMPT="$PROMPT

Return exactly one JSON object with keys verdict (pass|changes), summary, blockers
[{file,line,severity(critical|high),why}], notes [{file,line,note}]."

KIMI_DISABLE_TELEMETRY=1 "$KIMI_BIN" --agent-file "$REVIEW_DIR/kimi-agent.md" \
    --output-format stream-json -m "$KIMI_MODEL" -p "$PROMPT" >"$WORK/out" 2>"$WORK/err" \
    || advisory_unavailable "kimi CLI exited non-zero."

BODY="$(python3 -B "$REVIEW_DIR/verdict.py" --tool kimi --mode advisory --marker "$MARKER" \
    --head "$HEAD_SHA" --unavailable-reason-file "$WORK/unavailable" "$WORK/out")" \
    || advisory_unavailable "Could not render the review verdict."
# Advisory exit status stays zero; use the separate reason, not Markdown wording.
if [ -s "$WORK/unavailable" ]; then
    REASON="$(cat "$WORK/unavailable")" || advisory_unavailable "Could not read the review diagnostic."
    advisory_unavailable "$REASON" "$BODY"
fi
post_sticky "$MARKER" "$BODY" || true
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "completed=true" >> "$GITHUB_OUTPUT"
fi
echo "[kimi-review] advisory complete; never blocking"
exit 0
