#!/usr/bin/env bash
# Advisory kimi review, run by .github/workflows/kimi-review.yml. Never fails:
# findings and unavailability are posted as a sticky comment; exit is always 0.
# Same trust model as codex-review.sh: trusted base checkout, PR head read as diff only.
#
# Env: PR_NUMBER BASE_SHA HEAD_SHA BASE_REPO GH_TOKEN SHARED_CI_DIR
# Optional: KIMI_BIN, KIMI_MODEL, KIMI_MODEL_GROUP, KIMI_LAUNCHER,
# REVIEW_MODEL_GROUP, REVIEW_SERVED_MODEL, REVIEW_RULES_FILE, REVIEW_MAX_BYTES,
# REVIEW_MARKER.
set -uo pipefail

REVIEW_DIR="${SHARED_CI_DIR:-.}/scripts/review"
MARKER="${REVIEW_MARKER:-<!-- shared-ci-kimi-review -->}"
MAX_BYTES="${REVIEW_MAX_BYTES:-40000}"
KIMI_BIN="${KIMI_BIN:-kimi}"
KIMI_MODEL="${KIMI_MODEL:-${KIMI_MODEL_GROUP:-${REVIEW_MODEL_GROUP:-kimi-code/k3}}}"
KIMI_MAX_ATTEMPTS="${KIMI_MAX_ATTEMPTS:-1}"
case "$KIMI_MAX_ATTEMPTS" in
    ''|*[!0-9]*|0) KIMI_MAX_ATTEMPTS=1 ;;
esac

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
        if [ -n "$body" ]; then
            :
        elif [ -n "${REVIEW_SERVED_MODEL:-}" ]; then
            body="$(python3 -B "$REVIEW_DIR/verdict.py" --tool kimi --mode advisory --marker "$MARKER" \
                --head "${HEAD_SHA:-unknown}" --served-model "$REVIEW_SERVED_MODEL" --unavailable "$1")"
        else
            body="$(python3 -B "$REVIEW_DIR/verdict.py" --tool kimi --mode advisory --marker "$MARKER" \
                --head "${HEAD_SHA:-unknown}" --unavailable "$1")"
        fi
        if [ -n "$body" ]; then
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

if [ "${KIMI_FORCE_RERUN:-}" != "1" ]; then
    if python3 -I -B -c '
import json
import os
import re
import subprocess
import sys

marker = sys.argv[1]
legacy = "<!-- kimi-advisory-review -->"
completed = (
    "kimi advisory review: pass",
    "kimi advisory review: findings",
    "## \u2705 Kimi advisory review",
    "## \u26a0\ufe0f Kimi advisory review",
    "## \U0001f534 Kimi advisory review",
)
bots = {"github-actions", "github-actions[bot]"}
repo = os.environ.get("BASE_REPO", "")
pr = os.environ.get("PR_NUMBER", "")
if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not re.fullmatch(r"[1-9][0-9]*", pr):
    sys.exit(1)
owner, name = repo.split("/", 1)
query = """query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
  repository(owner:$owner,name:$name) { pullRequest(number:$number) {
    comments(first:100,after:$cursor) {
      nodes { body author { login } editor { login } createdAt updatedAt }
      pageInfo { hasNextPage endCursor }
    }
  } }
}"""
cursor, latest = None, None
while True:
    args = ["gh", "api", "graphql", "-f", "query=" + query,
            "-f", "owner=" + owner, "-f", "name=" + name, "-F", "number=" + pr]
    if cursor:
        args += ["-f", "cursor=" + cursor]
    proc = subprocess.run(args, capture_output=True, encoding="utf-8", timeout=60)
    if proc.returncode != 0:
        sys.exit(1)
    data = json.loads(proc.stdout)
    if data.get("errors"):
        sys.exit(1)
    page = data["data"]["repository"]["pullRequest"]["comments"]
    for comment in page["nodes"]:
        body = comment.get("body") or ""
        if marker in body or legacy in body:
            latest = comment
    info = page["pageInfo"]
    if not info["hasNextPage"]:
        break
    if not info["endCursor"] or cursor == info["endCursor"]:
        sys.exit(1)
    cursor = info["endCursor"]
if latest is None:
    sys.exit(1)
editor = latest.get("editor")
if ((latest.get("author") or {}).get("login") not in bots
        or (editor is not None and editor.get("login") not in bots)
        or (latest.get("createdAt") != latest.get("updatedAt") and editor is None)):
    sys.exit(1)
body = latest.get("body") or ""
if "unavailable" in body.lower():
    sys.exit(1)
if any(token in body for token in completed):
    sys.exit(0)
sys.exit(1)
' "$MARKER" >/dev/null 2>&1; then
        echo "[kimi-review] PR #$PR_NUMBER already has a completed Kimi review; skipping per once-per-PR quota policy."
        exit 0
    fi
fi

command -v "$KIMI_BIN" >/dev/null 2>&1 || advisory_unavailable "kimi CLI is not installed on the runner."
git fetch --no-tags --depth=200 origin "$BASE_SHA" "$HEAD_SHA" >/dev/null 2>&1 \
    || advisory_unavailable "Could not fetch the exact PR revisions."
# Read the immutable base blob, never mutable worktree or PR-head instructions.
python3 -B "$REVIEW_DIR/rules_input.py" "$BASE_SHA" "${REVIEW_RULES_FILE:-AGENTS.md}" >"$WORK/rules" \
    || advisory_unavailable "Trusted-base repository rules are missing or invalid."

PROMPT_ARGS=(--rules-file "$WORK/rules")
if python3 -I -B "$REVIEW_DIR/owner_decisions.py" >"$WORK/owner" 2>/dev/null; then
    PROMPT_ARGS+=(--owner-file "$WORK/owner")
fi
PR_OK=0
if python3 -I -B "$REVIEW_DIR/pr_text.py" --record-file "$WORK/pr.json" >"$WORK/pr" 2>/dev/null; then
    PROMPT_ARGS+=(--pr-file "$WORK/pr")
    PR_OK=1
elif python3 -I -B "$REVIEW_DIR/pr_text.py" >"$WORK/pr" 2>/dev/null; then
    PROMPT_ARGS+=(--pr-file "$WORK/pr")
fi

git diff --no-ext-diff --find-renames --unified=15 "$BASE_SHA...$HEAD_SHA" >"$WORK/diff" 2>/dev/null \
    || advisory_unavailable "Could not compute the PR diff."
git diff --name-only "$BASE_SHA...$HEAD_SHA" >"$WORK/changed" 2>/dev/null || true
[ -s "$WORK/changed" ] || { post_sticky "$MARKER" "$MARKER
## kimi advisory review: pass

No committed diff." || true; exit 0; }
if ! grep -vqE '\.md$' "$WORK/changed"; then
    post_sticky "$MARKER" "$MARKER
## kimi advisory review: pass

Reviewed head: \`$HEAD_SHA\`

No non-documentation code changes; skipped Kimi LLM invocation to conserve quota.

<sub>Advisory only: this check never blocks merge.</sub>" || true
    echo "[kimi-review] docs-only diff; skipped Kimi LLM invocation to conserve quota"
    exit 0
fi
if [ "$PR_OK" -eq 1 ] && git diff --name-only --no-renames -z "$BASE_SHA...$HEAD_SHA" >"$WORK/changed.nul" 2>/dev/null; then
    if python3 -I -B "$REVIEW_DIR/target_scope.py" "$WORK/pr.json" "$WORK/changed.nul" "$WORK/scope.json" >"$WORK/scope-prompt" 2>/dev/null; then
        PROMPT_ARGS+=(--scope-file "$WORK/scope-prompt")
    fi
fi

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

KIMI_RC=0
KIMI_ATTEMPT=1
while :; do
    : >"$WORK/out"
    : >"$WORK/err"
    # shellcheck disable=SC2206 # intentional word split of a trusted launcher prefix
    LAUNCHER=(${KIMI_LAUNCHER:-})
    if [ "${#LAUNCHER[@]}" -gt 0 ]; then
        KIMI_DISABLE_TELEMETRY=1 "${LAUNCHER[@]}" "$KIMI_BIN" --agent-file "$REVIEW_DIR/kimi-agent.md" \
            --output-format stream-json -m "$KIMI_MODEL" -p "$PROMPT" >"$WORK/out" 2>"$WORK/err"
        KIMI_RC=$?
    else
        KIMI_DISABLE_TELEMETRY=1 "$KIMI_BIN" --agent-file "$REVIEW_DIR/kimi-agent.md" \
            --output-format stream-json -m "$KIMI_MODEL" -p "$PROMPT" >"$WORK/out" 2>"$WORK/err"
        KIMI_RC=$?
    fi
    if [ "$KIMI_RC" -eq 0 ]; then
        break
    fi
    if [ "$KIMI_ATTEMPT" -ge "$KIMI_MAX_ATTEMPTS" ]; then
        break
    fi
    KIMI_ATTEMPT=$((KIMI_ATTEMPT + 1))
done

if [ "$KIMI_RC" -ne 0 ]; then
    KIMI_FAIL_REASON="$(python3 -I -B -c '
import pathlib
import re
import sys

rc = sys.argv[1]
err_path = pathlib.Path(sys.argv[2])
try:
    raw = err_path.read_text(encoding="utf-8", errors="replace")
except OSError:
    raw = ""
raw = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw)
lines = [line.strip() for line in raw.splitlines() if line.strip()]
if not lines:
    print("kimi CLI exited non-zero.")
    sys.exit(0)
last = lines[-1]
last = re.sub(
    r"(?i)\b(bearer|token|api[_-]?key|secret|password|authorization)\s*([:=]|\s+)\s*\S+",
    r"\1=[redacted]",
    last,
)
last = re.sub(
    r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github[_]pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{8,}|xox[baprs]-[0-9A-Za-z-]+)\b",
    "[redacted]",
    last,
)
last = re.sub(r"(?<![A-Za-z0-9_.-])/(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]*", "[path]", last)
last = re.sub(r"[\x00-\x1f\x7f]+", " ", last)
last = " ".join(last.split())
last = last.replace("@", "＠").replace("<", "‹").replace("\x60", "´")[:200].rstrip(".")
if not last:
    print("kimi CLI exited non-zero.")
else:
    print(f"kimi CLI exited non-zero (exit {rc}: {last}).")
' "$KIMI_RC" "$WORK/err" 2>/dev/null)" || KIMI_FAIL_REASON="kimi CLI exited non-zero."
    advisory_unavailable "${KIMI_FAIL_REASON:-kimi CLI exited non-zero.}"
fi

RENDER_RC=0
if [ -n "${REVIEW_SERVED_MODEL:-}" ]; then
    BODY="$(python3 -B "$REVIEW_DIR/verdict.py" --tool kimi --mode advisory --marker "$MARKER" \
        --head "$HEAD_SHA" --served-model "$REVIEW_SERVED_MODEL" \
        --unavailable-reason-file "$WORK/unavailable" "$WORK/out")" || RENDER_RC=$?
else
    BODY="$(python3 -B "$REVIEW_DIR/verdict.py" --tool kimi --mode advisory --marker "$MARKER" \
        --head "$HEAD_SHA" --unavailable-reason-file "$WORK/unavailable" "$WORK/out")" || RENDER_RC=$?
fi
[ "$RENDER_RC" -eq 0 ] || advisory_unavailable "Could not render the review verdict."
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
