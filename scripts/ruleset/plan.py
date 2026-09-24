#!/usr/bin/env python3
"""Plan a default-branch ruleset change: old -> new, from fixtures or API dumps.

Inputs are JSON files (apply.sh fetches them; tests use fixtures):
  --current   GET repos/{o}/{r}/rules/branches/main   (effective rules, any ruleset)
  --rulesets  GET repos/{o}/{r}/rulesets               (list)
  --detail    GET repos/{o}/{r}/rulesets/{id}          (the ruleset whose name matches
              the template; omit when none exists)
Desired state = templates/ruleset.json plus:
  * every currently required check is PRESERVED unless mapped with --map OLD=NEW
    (NEW empty = explicit removal); a map for a check that is not required fails;
  * --extra-check NAME adds caller checks;
  * --strict opts into strict (up-to-date branch) checks (default false);
  * --no-code-owner-review keeps code-owner review off (transition period).
Output: plan JSON on stdout (action create|update|noop, ruleset_id, diff, payload).
`--verify READBACK` compares a post-apply `rules/branches/main` dump with a plan.
Exit 0 ok, 1 verification mismatch, 2 invalid input.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE.parents[1] / "templates" / "ruleset.json"
CHECKS = "required_status_checks"
PAYLOAD_KEYS = ("name", "target", "enforcement", "conditions", "bypass_actors", "rules")


class PlanError(ValueError):
    """Input is inconsistent; nothing may be applied."""


def _load(path: str | None, default: Any = None) -> Any:
    if path is None:
        return default
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PlanError(f"cannot read {path}: {error}") from None


def _rules_by_type(rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for rule in rules or []:
        if not isinstance(rule, dict) or not isinstance(rule.get("type"), str):
            raise PlanError("rules must be objects with a type")
        result.setdefault(rule["type"], rule)
    return result


def _contexts(rule: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not rule:
        return []
    checks = (rule.get("parameters") or {}).get(CHECKS) or []
    return [{k: v for k, v in check.items() if k in ("context", "integration_id")}
            for check in checks if isinstance(check, dict) and isinstance(check.get("context"), str)]


def _parse_maps(values: list[str]) -> dict[str, str]:
    maps: dict[str, str] = {}
    for value in values:
        old, sep, new = value.partition("=")
        if not sep or not old.strip():
            raise PlanError(f"--map needs OLD=NEW (NEW may be empty to remove): {value!r}")
        maps[old.strip()] = new.strip()
    return maps


def desired(template: dict[str, Any], current_checks: list[dict[str, Any]], *, extra: list[str],
            maps: dict[str, str], strict: bool, code_owner: bool) -> dict[str, Any]:
    payload = {key: copy.deepcopy(template[key]) for key in PAYLOAD_KEYS if key in template}
    rules = _rules_by_type(payload["rules"])
    current_names = [check["context"] for check in current_checks]
    unknown = sorted(set(maps) - set(current_names))
    if unknown:
        raise PlanError(f"--map names checks that are not currently required: {unknown}")
    wanted: list[dict[str, Any]] = []

    def add(check: dict[str, Any]) -> None:
        if check["context"] and all(item["context"] != check["context"] for item in wanted):
            wanted.append(check)

    for check in _contexts(rules.get(CHECKS)):
        add(check)
    for name in extra:
        add({"context": name})
    for check in current_checks:
        name = check["context"]
        if name in maps:
            if maps[name]:
                add({"context": maps[name]})
        else:
            add(dict(check))
    if CHECKS in rules:
        parameters = rules[CHECKS].setdefault("parameters", {})
        parameters[CHECKS] = wanted
        parameters["strict_required_status_checks_policy"] = bool(strict)
    if "pull_request" in rules:
        rules["pull_request"].setdefault("parameters", {})["require_code_owner_review"] = bool(code_owner)
    return payload


def _rule_changes(old: dict[str, dict], new: dict[str, dict]) -> list[str]:
    changes = []
    for rule_type in sorted(set(old) | set(new)):
        if rule_type not in old:
            changes.append(f"+ rule {rule_type}")
        elif rule_type not in new:
            changes.append(f"- rule {rule_type} (kept: not managed by the template)")
        else:
            before, after = old[rule_type].get("parameters") or {}, new[rule_type].get("parameters") or {}
            for key in sorted(set(before) | set(after)):
                if key == CHECKS:
                    continue
                if before.get(key) != after.get(key):
                    changes.append(f"~ {rule_type}.{key}: {json.dumps(before.get(key))} -> {json.dumps(after.get(key))}")
    return changes


def plan(template: dict[str, Any], current: list[dict[str, Any]], rulesets: list[dict[str, Any]],
         detail: dict[str, Any] | None, *, extra: list[str], maps: dict[str, str], strict: bool,
         code_owner: bool) -> dict[str, Any]:
    if not isinstance(current, list) or not isinstance(rulesets, list):
        raise PlanError("--current and --rulesets must be JSON arrays")
    matching = [item for item in rulesets if isinstance(item, dict) and item.get("name") == template["name"]]
    if len(matching) > 1:
        raise PlanError(f"more than one ruleset is named {template['name']!r}")
    target_id = matching[0].get("id") if matching else None
    if target_id is not None and (not isinstance(detail, dict) or detail.get("id") != target_id):
        raise PlanError(f"--detail must be ruleset {target_id} ({template['name']!r})")
    current_rules = _rules_by_type(current)
    # Preserve every check the branch currently requires, from any ruleset.
    current_checks = [check for rule in current if isinstance(rule, dict) and rule.get("type") == CHECKS
                      for check in _contexts(rule)]
    seen: set[str] = set()
    current_checks = [c for c in current_checks if not (c["context"] in seen or seen.add(c["context"]))]
    payload = desired(template, current_checks, extra=extra, maps=maps, strict=strict, code_owner=code_owner)
    old_payload = {key: detail.get(key) for key in PAYLOAD_KEYS} if target_id is not None else None
    old_rules = _rules_by_type(old_payload["rules"]) if old_payload else current_rules
    new_rules = _rules_by_type(payload["rules"])
    if old_payload:
        # Unmanaged rules and unmanaged parameters of the managed ruleset are kept, not dropped.
        for rule_type, rule in old_rules.items():
            if rule_type not in new_rules:
                payload["rules"].append(copy.deepcopy(rule))
            elif rule.get("parameters"):
                merged = copy.deepcopy(rule["parameters"])
                merged.update(new_rules[rule_type].get("parameters") or {})
                new_rules[rule_type]["parameters"] = merged
        new_rules = _rules_by_type(payload["rules"])
    old_names = [check["context"] for check in current_checks]
    new_names = [check["context"] for check in _contexts(new_rules.get(CHECKS))]
    others = sorted({rule.get("ruleset_id") for rule in current if isinstance(rule, dict)
                     and rule.get("ruleset_id") not in (None, target_id)}, key=str)
    changed = old_payload != payload
    return {
        "action": "create" if target_id is None else ("update" if changed else "noop"),
        "ruleset_id": target_id,
        "other_rulesets": others,
        "diff": {
            "checks_old": old_names, "checks_new": new_names,
            "checks_added": [n for n in new_names if n not in old_names],
            "checks_removed": [n for n in old_names if n not in new_names],
            "mapped": maps,
            "rules": _rule_changes(old_rules, new_rules),
            "bypass_actors": {"old": (old_payload or {}).get("bypass_actors"), "new": payload["bypass_actors"]},
        },
        "payload": payload,
    }


def verify(plan_data: dict[str, Any], readback: list[dict[str, Any]]) -> list[str]:
    problems = []
    effective = [check["context"] for rule in readback if isinstance(rule, dict) and rule.get("type") == CHECKS
                 for check in _contexts(rule)]
    for name in plan_data["diff"]["checks_new"]:
        if name not in effective:
            problems.append(f"required check missing after apply: {name}")
    types = {rule.get("type") for rule in readback if isinstance(rule, dict)}
    for rule in plan_data["payload"]["rules"]:
        if rule["type"] not in types:
            problems.append(f"rule missing after apply: {rule['type']}")
    return problems


def text_summary(result: dict[str, Any]) -> str:
    diff = result["diff"]
    lines = [f"action: {result['action']} (ruleset id: {result['ruleset_id'] or 'new'})",
             "required checks (old -> new):",
             f"  old: {diff['checks_old']}", f"  new: {diff['checks_new']}"]
    lines += [f"  + {name}" for name in diff["checks_added"]]
    lines += [f"  - {name}" for name in diff["checks_removed"]]
    lines += [f"  {line}" for line in diff["rules"]]
    if result["other_rulesets"]:
        lines.append(f"other rulesets on the branch (untouched): {result['other_rulesets']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ruleset-plan")
    parser.add_argument("--template", default=str(TEMPLATE))
    parser.add_argument("--current", required=True)
    parser.add_argument("--rulesets", required=True)
    parser.add_argument("--detail")
    parser.add_argument("--extra-check", action="append", default=[])
    parser.add_argument("--map", action="append", default=[])
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-code-owner-review", action="store_true")
    parser.add_argument("--verify", metavar="READBACK", help="check a post-apply rules dump against --plan")
    parser.add_argument("--plan", help="plan JSON (with --verify)")
    parser.add_argument("--summary", action="store_true", help="print a text summary to stderr")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            problems = verify(_load(args.plan), _load(args.verify))
            for problem in problems:
                print(problem, file=sys.stderr)
            print(json.dumps({"ok": not problems, "problems": problems}))
            return 0 if not problems else 1
        result = plan(_load(args.template), _load(args.current), _load(args.rulesets), _load(args.detail),
                      extra=args.extra_check, maps=_parse_maps(args.map), strict=args.strict,
                      code_owner=not args.no_code_owner_review)
    except PlanError as error:
        print(f"ruleset-plan: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.summary:
        print(text_summary(result), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
