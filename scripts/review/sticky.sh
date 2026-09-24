# Sourced helper: maintain one sticky PR comment identified by a marker.
# Requires PR_NUMBER, BASE_REPO and an authenticated `gh` (GH_TOKEN).
# post_sticky MARKER BODY -> updates the newest comment containing MARKER or creates one.
post_sticky() {
    local marker="$1" body="$2" id
    id="$(gh api "repos/$BASE_REPO/issues/$PR_NUMBER/comments" --paginate \
        --jq "[.[] | select(.body | contains(\"$marker\"))] | last | .id" 2>/dev/null || true)"
    if [ -n "$id" ] && [ "$id" != "null" ]; then
        gh api -X PATCH "repos/$BASE_REPO/issues/comments/$id" -f body="$body" >/dev/null 2>&1 && return 0
    fi
    gh api -X POST "repos/$BASE_REPO/issues/$PR_NUMBER/comments" -f body="$body" >/dev/null 2>&1 || {
        echo "[review] could not post the PR comment" >&2
        return 1
    }
}
