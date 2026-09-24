#!/usr/bin/env bash
# Plan (default) or apply the shared-ci default-branch ruleset, then read back.
#
#   scripts/ruleset/apply.sh OWNER/REPO [plan options]            # dry run: print old -> new
#   scripts/ruleset/apply.sh OWNER/REPO [plan options] --apply    # apply, then verify readback
#
# Plan options are passed to plan.py: --extra-check NAME, --map OLD=NEW, --strict,
# --no-code-owner-review, --template FILE. Uses the caller's authenticated `gh`.
# Ruleset changes are important: run the dry run, get Owner approval, then --apply.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
[ "$#" -ge 1 ] || { echo "usage: $0 OWNER/REPO [plan options] [--apply]" >&2; exit 2; }
repo="$1"; shift
case "$repo" in */*) ;; *) echo "repository must be OWNER/REPO" >&2; exit 2 ;; esac

apply=0
options=()
for arg in "$@"; do
    if [ "$arg" = "--apply" ]; then apply=1; else options+=("$arg"); fi
done

work="$(mktemp -d -t ruleset-plan.XXXXXX)"
trap 'rm -rf "$work"' EXIT
python="${PYTHON:-python3}"
template="$here/../../templates/ruleset.json"
for ((i = 0; i < ${#options[@]}; i++)); do
    [ "${options[$i]}" = "--template" ] && template="${options[$((i + 1))]}"
done
name="$("$python" -c 'import json,sys;print(json.load(open(sys.argv[1]))["name"])' "$template")"

gh api "repos/$repo/rules/branches/main" >"$work/current.json"
gh api "repos/$repo/rulesets" >"$work/rulesets.json"
id="$("$python" -c 'import json,sys
items=[r for r in json.load(open(sys.argv[1])) if r.get("name")==sys.argv[2]]
print(items[0]["id"] if len(items)==1 else "")' "$work/rulesets.json" "$name")"
detail=()
if [ -n "$id" ]; then
    gh api "repos/$repo/rulesets/$id" >"$work/detail.json"
    detail=(--detail "$work/detail.json")
fi

"$python" "$here/plan.py" --current "$work/current.json" --rulesets "$work/rulesets.json" \
    ${detail[@]+"${detail[@]}"} ${options[@]+"${options[@]}"} --summary >"$work/plan.json"
action="$("$python" -c 'import json,sys;print(json.load(open(sys.argv[1]))["action"])' "$work/plan.json")"

if [ "$apply" -ne 1 ]; then
    echo "[ruleset] dry run for $repo: $action (re-run with --apply after Owner approval)"
    exit 0
fi
"$python" -c 'import json,sys;json.dump(json.load(open(sys.argv[1]))["payload"],open(sys.argv[2],"w"))' \
    "$work/plan.json" "$work/payload.json"
case "$action" in
    noop) echo "[ruleset] $repo already matches; nothing applied" ;;
    create) gh api -X POST "repos/$repo/rulesets" --input "$work/payload.json" >/dev/null ;;
    update) gh api -X PUT "repos/$repo/rulesets/$id" --input "$work/payload.json" >/dev/null ;;
    *) echo "[ruleset] unknown action $action" >&2; exit 2 ;;
esac
gh api "repos/$repo/rules/branches/main" >"$work/readback.json"
"$python" "$here/plan.py" --current "$work/current.json" --rulesets "$work/rulesets.json" \
    --verify "$work/readback.json" --plan "$work/plan.json"
echo "[ruleset] $repo: $action applied and read back"
