#!/usr/bin/env python3
"""Report actionable stuck PR signals; never repair, rerun, approve or merge."""
import datetime as dt
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request

TITLE = "[stuck-PR bot] open stuck PRs"
SUMMARY = "<!-- stuck-pr-bot:summary:v1 -->"
STATE = "<!-- stuck-pr-bot:state:v2\n"
BOT = "github-actions[bot]"
FAILED = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE"}
GTT = re.compile(r"(?:MY-\d+|TK\w+|(?:^|[/:])gtt/)", re.I)

QUERY = """
query($owner:String!, $repo:String!, $number:Int!, $cursor:String, $thread_cursor:String) {
  repository(owner:$owner, name:$repo) {
    pullRequest(number:$number) {
      state isDraft headRefOid headRefName createdAt title body
      mergeable mergeStateStatus reviewDecision
      author { login }
      labels(first:100) { nodes { name } }
      autoMergeRequest { enabledAt }
      reviewRequests(first:100) { nodes { requestedReviewer { ... on User { login } ... on Team { slug } } } }
      reviewThreads(first:100, after:$thread_cursor) { nodes { isResolved isOutdated comments(first:1) { nodes { createdAt } } } pageInfo { hasNextPage endCursor } }
      commits(last:1) { nodes { commit {
        oid
        statusCheckRollup { contexts(first:100, after:$cursor) {
          pageInfo { hasNextPage endCursor }
          nodes {
            ... on CheckRun { name databaseId conclusion status completedAt isRequired(pullRequestNumber:$number) checkSuite { app { databaseId } } }
            ... on StatusContext { context state createdAt isRequired(pullRequestNumber:$number) }
          }
        } }
      } } }
    }
  }
}
"""


def instant(value):
    if not isinstance(value, str): raise ValueError("Timestamp unavailable")
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None: raise ValueError("Timestamp has no timezone")
    return result


def threshold(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0: raise ValueError("Thresholds must be finite positive numbers")
    return result


def positive_int_list(value):
    if not value: return set()
    result = set()
    for part in value.split(","):
        if not re.fullmatch(r"[1-9]\d*", part.strip()): raise ValueError("PR lists must contain positive integers")
        result.add(int(part))
    return result


def allowlist(value):
    result = {part.strip().lower() for part in value.split(",") if part.strip()}
    if any(not re.fullmatch(r"[A-Za-z0-9-]+", item) for item in result): raise ValueError("Invalid mention login")
    return result


def login(value):
    if value and not re.fullmatch(r"[A-Za-z0-9-]+", value): raise ValueError("Invalid GitHub login")
    return value


def quoted(value):
    value = " ".join(str(value).split())[:300].replace("@", "＠")
    return re.sub(r"([\\`*_{}\[\]()<>!|])", r"\\\1", value)


def state_json(value):
    """Serialize state without allowing untrusted text to close its HTML comment."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).replace("-->", r"--\u003e")


def failures(contexts):
    latest = {}
    for item in contexts:
        if "name" in item:
            app = (item.get("checkSuite") or {}).get("app") or {}
            key, rank = ("check", item["name"], app.get("databaseId")), item.get("databaseId", 0)
            name = item["name"]
            failed = item.get("status") == "COMPLETED" and item.get("conclusion") in FAILED
            completed = item.get("completedAt")
        else:
            key, rank = ("status", item["context"]), instant(item["createdAt"])
            name, failed = item["context"], item.get("state") in {"ERROR", "FAILURE"}
            completed = item["createdAt"]
        if key not in latest or rank > latest[key][0]: latest[key] = (rank, name, item.get("isRequired"), failed, completed)
    current = []
    for _, name, required, failed, completed in latest.values():
        if required and failed:
            if completed is None: raise ValueError("Failed required check has no completion timestamp")
            current.append((name, instant(completed)))
    return sorted({name for name, _ in current}), min((when for _, when in current), default=None)


def failure_attempts(contexts):
    return sorted(str(item.get("databaseId")) for item in contexts
                  if "name" in item and item.get("isRequired") and
                  item.get("status") == "COMPLETED" and item.get("conclusion") in FAILED)


def _thread_info(pr, now, thread_hours):
    result, unknown = [], False
    for thread in pr.get("threads", []):
        if not thread.get("isResolved") and not thread.get("isOutdated"):
            comments = thread.get("comments", {}).get("nodes", [])
            if not comments or not comments[0].get("createdAt"):
                unknown = True
            elif (now - instant(comments[0]["createdAt"])).total_seconds() / 3600 > thread_hours:
                result.append(thread)
    return len(result), unknown


def default_options(failure_hours=2, open_hours=24):
    return {"failure_hours": threshold(failure_hours), "open_hours": threshold(open_hours), "stale_days": 14,
            "draft_days": 7, "auto_merge_grace_minutes": 30, "thread_hours": 24, "mention_allowlist": set(),
            "summary_assignee": "", "exclude_prs": set(), "auto_merge_exempt_prs": set()}


def classify(pr, now, options):
    if pr["state"] != "OPEN": return None
    age = (now - instant(pr["createdAt"])).total_seconds() / 3600
    failed, completed = failures(pr.get("contexts", []))
    elapsed = (now - completed).total_seconds() / 3600 if completed else None
    auto = bool(pr.get("autoMergeRequest"))
    mergeable, merge_state, review = pr.get("mergeable"), pr.get("mergeStateStatus"), pr.get("reviewDecision")
    threads, thread_unknown = _thread_info(pr, now, options["thread_hours"])
    number = pr.get("number")
    exception = number in options["auto_merge_exempt_prs"]
    actionable = []
    if elapsed is not None and elapsed >= options["failure_hours"]: actionable.append(f"required checks failed for {elapsed:.1f}h")
    if not pr.get("isDraft") and not auto and not exception and age > options["auto_merge_grace_minutes"] / 60: actionable.append("auto-merge is not enabled")
    if mergeable == "CONFLICTING" or merge_state in {"CONFLICTING", "DIRTY"}: actionable.append("merge conflict")
    if review == "CHANGES_REQUESTED": actionable.append("changes requested")
    if merge_state == "BEHIND" and not auto and not exception: actionable.append("branch is behind main")
    stale, draft_old = age > options["stale_days"] * 24, pr.get("isDraft") and age > options["draft_days"] * 24
    reasons = list(actionable)
    if stale: reasons.append("stale")
    if draft_old: reasons.append("Draft open too long")
    if age > options["open_hours"]: reasons.append(f"open for {age:.1f}h")
    if threads: reasons.append(f"{threads} unresolved discussion thread(s) older than {options['thread_hours']:g}h")
    if thread_unknown: reasons.append("unresolved discussion age unknown; review next run")
    if pr.get("reviewRequests"): reasons.append("manual review requested")
    if pr.get("labels_owner_review"): reasons.append("owner-review label remains")
    if pr.get("mergeable") in {None, "UNKNOWN"} or pr.get("mergeStateStatus") in {None, "UNKNOWN"}:
        reasons.append("merge state unknown; review next run")
    if not reasons: return None
    return {"number": number, "head": pr["headRefOid"], "classification": "actionable" if actionable and not pr.get("isDraft") and not stale else "summary-only",
            "reasons": reasons, "age_hours": round(age, 1), "auto_merge": auto, "mergeable": mergeable, "merge_state": merge_state,
            "review_decision": review, "draft": bool(pr.get("isDraft")), "unresolved_threads": threads,
            "thread_unknown": thread_unknown,
            "gtt_present": bool(pr.get("gtt_present")), "stale": stale, "exception": exception, "repeat_failure": False,
            "failed": failed, "failure_attempts": failure_attempts(pr.get("contexts", [])),
            "failure_completed": completed.isoformat() if completed else None, "author": (pr.get("author") or {}).get("login", "")}


def report(pr, now, failure_hours, open_hours, mention_allowlist=None, options=None):
    head = pr.get("headRefOid")
    commit = pr.get("commits", {}).get("nodes", [{}])[-1].get("commit", {})
    if not re.fullmatch(r"[0-9a-f]{40}", head or "") or commit.get("oid") != head:
        raise ValueError("Head and check commit differ")
    options = options or default_options(failure_hours, open_hours)
    if mention_allowlist is not None: options["mention_allowlist"] = mention_allowlist if isinstance(mention_allowlist, set) else allowlist(mention_allowlist)
    result = classify(pr, now, options)
    if not result or result["classification"] != "actionable": return None
    rendered = []
    for name in result["failed"]:
        safe = quoted(name)
        if len("; ".join(rendered + [safe])) > 50000: break
        rendered.append(safe)
    names = ", ".join(rendered) or "none observed"
    if len(rendered) < len(result["failed"]): names += f"; {len(result['failed']) - len(rendered)} more failed required checks (see this PR's checks tab)"
    mention = f" @{result['author']}" if result["author"].lower() in options["mention_allowlist"] else ""
    return (f"<!-- stuck-pr-bot:v1 head={result['head']} -->\n## Stuck PR report\n\nHead: `{result['head']}`\n\n"
            f"{'; '.join(result['reasons'])}.{mention}\n\nFailed required checks: {names}.\n\nPR age: {result['age_hours']:.1f} hours.\n\n"
            "Bot 不会修 (the bot will not repair). This bot only reports; it never reruns checks, approves, changes labels or auto-merge, or merges.\n")


class API:
    def __init__(self, repository, token):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository): raise ValueError("Invalid repository")
        self.repository, self.token = repository, token

    def request(self, method, path, body=None):
        graphql = path == "graphql"
        base = os.environ.get("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql") if graphql else os.environ.get("GITHUB_API_URL", "https://api.github.com") + "/"
        url = base if graphql else base + path
        request = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(), headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json", "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl): return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response: return json.load(response)

    def rest(self, method, suffix, body=None): return self.request(method, "repos/" + self.repository + "/" + suffix, body)

    def pages(self, suffix):
        page = 1
        while True:
            rows = self.rest("GET", suffix + ("&" if "?" in suffix else "?") + f"per_page=100&page={page}")
            if not isinstance(rows, list): raise ValueError("Invalid paginated response")
            yield from rows
            if len(rows) < 100: break
            page += 1

    def snapshot(self, number):
        owner, repo = self.repository.split("/")
        cursor, thread_cursor, contexts, threads = None, None, [], []
        context_done, thread_done, seen_cursors, seen_thread_cursors = False, False, set(), set()
        expected_head = None
        while True:
            data = self.request("POST", "graphql", {"query": QUERY, "variables": {"owner": owner, "repo": repo, "number": number, "cursor": cursor, "thread_cursor": thread_cursor}})
            if data.get("errors"): raise ValueError("GitHub query failed")
            pr = data["data"]["repository"]["pullRequest"]
            if pr is None: raise ValueError("PR unavailable")
            if expected_head is None: expected_head = pr.get("headRefOid")
            if pr.get("headRefOid") != expected_head: raise ValueError("Head changed during pagination")
            commit = pr["commits"]["nodes"][-1]["commit"]
            if commit["oid"] != pr["headRefOid"]: raise ValueError("Head and check commit differ")
            rollup = commit["statusCheckRollup"]
            if not context_done and rollup:
                contexts.extend(rollup["contexts"]["nodes"])
                info = rollup["contexts"]["pageInfo"]
                if info["hasNextPage"]:
                    next_cursor = info.get("endCursor")
                    if not next_cursor or next_cursor in seen_cursors: raise ValueError("Invalid context pagination cursor")
                    seen_cursors.add(next_cursor); cursor = next_cursor; continue
                context_done = True; cursor = None
            if not thread_done:
                threads.extend(pr.get("reviewThreads", {}).get("nodes", []))
                tinfo = pr.get("reviewThreads", {}).get("pageInfo", {})
                if tinfo.get("hasNextPage"):
                    next_cursor = tinfo.get("endCursor")
                    if not next_cursor or next_cursor in seen_thread_cursors: raise ValueError("Invalid thread pagination cursor")
                    seen_thread_cursors.add(next_cursor); thread_cursor = next_cursor; continue
                thread_done = True
            pr["contexts"], pr["threads"] = contexts, threads
            pr["reviewRequests"] = [node.get("requestedReviewer") for node in pr.get("reviewRequests", {}).get("nodes", []) if node.get("requestedReviewer")]
            pr["labels_owner_review"] = any(node.get("name") == "owner-review" for node in pr.get("labels", {}).get("nodes", []))
            pr["gtt_present"] = bool(GTT.search((pr.get("headRefName") or "") + " " + (pr.get("title") or "") + " " + (pr.get("body") or "")))
            return pr


def owned(item, marker):
    return item.get("user", {}).get("login") == BOT and item.get("user", {}).get("type") == "Bot" and (item.get("body") or "").startswith(marker)


def read_state(summary):
    """Read exactly one summary issue; old shards are deliberately not merged."""
    if isinstance(summary, list):
        raise ValueError("Multiple stuck-pr summaries are not supported")
    if not isinstance(summary, dict):
        raise ValueError("Corrupt stuck-pr state")
    body = summary.get("body", "")
    if STATE not in body:
        return {"schema": 2, "last_run_at": None, "entries": [], "history": {}}
    start = body.index(STATE) + len(STATE)
    end = body.find("\n-->", start)
    if end < 0:
        raise ValueError("Corrupt stuck-pr-bot state")
    try:
        state = json.loads(body[start:end])
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("Corrupt stuck-pr-bot state") from error
    if state.get("schema") != 2 or not isinstance(state.get("entries"), list) or not isinstance(state.get("history"), dict):
        raise ValueError("Corrupt stuck-pr-bot state")
    entry_keys = set()
    for entry in state["entries"]:
        if not isinstance(entry, dict) or "number" not in entry or "head" not in entry:
            raise ValueError("Corrupt stuck-pr entry")
        if not isinstance(entry["number"], int) or isinstance(entry["number"], bool) or not isinstance(entry["head"], str):
            raise ValueError("Corrupt stuck-pr entry")
        key = (entry["number"], entry["head"])
        if key in entry_keys:
            raise ValueError("Conflicting duplicate stuck-pr entry")
        entry_keys.add(key)
    if any(not isinstance(key, str) for key in state["history"]):
        raise ValueError("Corrupt stuck-pr history")
    if state.get("last_run_at"):
        instant(state["last_run_at"])
    if "truncated" in state and not isinstance(state["truncated"], bool):
        raise ValueError("Corrupt stuck-pr truncation flag")
    if "omitted" in state and (not isinstance(state["omitted"], int) or isinstance(state["omitted"], bool) or state["omitted"] < 0):
        raise ValueError("Corrupt stuck-pr omitted count")
    return state


def state_history(previous, observed):
    history = dict(previous.get("history", {}))
    for key, current in observed.items():
        old = history.get(key, {})
        old_attempts = set(old.get("latest_failed_attempt_ids", []))
        current_attempts = set(current.get("latest_failed_attempt_ids", []))
        failed = bool(current["failed"])
        recovered_at = old.get("recovery_seen_at")
        if old.get("last_required_state") == "failed" and not failed:
            recovered_at = current.get("observed_at")
        repeat = failed and (bool(recovered_at) or (bool(old.get("seen_failed")) and old_attempts != current_attempts))
        history[key] = {"seen_failed": bool(old.get("seen_failed")) or failed,
                        "last_required_state": "failed" if failed else "success",
                        "latest_failed_attempt_ids": sorted(current_attempts),
                        "recovery_seen_at": recovered_at, "recurrent": bool(old.get("recurrent")) or repeat}
    return history


def run(api, now, **kwargs):
    options = default_options(kwargs.get("failure_hours", 2), kwargs.get("open_hours", 24))
    options.update({"stale_days": threshold(kwargs.get("stale_days", 14)), "draft_days": threshold(kwargs.get("draft_days", 7)), "auto_merge_grace_minutes": threshold(kwargs.get("auto_merge_grace_minutes", 30)), "thread_hours": threshold(kwargs.get("thread_hours", 24)), "mention_allowlist": allowlist(kwargs.get("mention_allowlist", "")), "summary_assignee": login(kwargs.get("summary_assignee", "")), "exclude_prs": positive_int_list(kwargs.get("exclude_prs", "")), "auto_merge_exempt_prs": positive_int_list(kwargs.get("auto_merge_exempt_prs", ""))})
    entries, observed = [], {}
    stamp = now.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for item in api.pages("pulls?state=open"):
        number = item["number"]
        if number in options["exclude_prs"]: continue
        pr = api.snapshot(number); pr["number"] = number
        observed[f"{number}:{pr['headRefOid']}"] = {"failed": bool(failures(pr.get("contexts", []))[0]),
                                                     "latest_failed_attempt_ids": failure_attempts(pr.get("contexts", [])),
                                                     "observed_at": stamp}
        entry = classify(pr, now, options)
        if entry: entries.append(entry)
    summaries = [item for item in api.pages("issues?state=all&creator=" + BOT) if "pull_request" not in item and owned(item, SUMMARY) and item["title"] == TITLE]
    summaries.sort(key=lambda item: (item.get("created_at", ""), item.get("number", 0)))
    summary = summaries[0] if summaries else None
    previous = read_state(summary) if summary else {"history": {}}
    history = state_history(previous, observed)
    history = {key: value for key, value in history.items() if key in observed}
    for entry in entries:
        current_history = history.get(f"{entry['number']}:{entry['head']}", {})
        entry["repeat_failure"] = bool(current_history.get("recurrent"))
    refreshed, pending_comments = [], []
    for entry in entries:
        pr = api.snapshot(entry["number"]); pr["number"] = entry["number"]
        if pr["headRefOid"] != entry["head"]:
            continue
        current = classify(pr, now, options)
        if current:
            current["repeat_failure"] = entry["repeat_failure"]
            refreshed.append(current)
            if current["classification"] == "actionable":
                body = report(pr, now, options["failure_hours"], options["open_hours"], options["mention_allowlist"], options)
                marker = f"<!-- stuck-pr-bot:v1 head={current['head']} -->"
                comments = list(api.pages(f"issues/{current['number']}/comments"))
                if not any(owned(comment, marker) for comment in comments):
                    pending_comments.append((current["number"], body))
                elif f"{current['number']}:{current['head']}" not in previous.get("history", {}):
                    current["repeat_failure"] = "unknown"
    entries = refreshed
    actionable = [entry for entry in entries if entry["classification"] == "actionable"]
    state_fields = ("number", "head", "classification", "reasons", "age_hours", "auto_merge", "mergeable", "merge_state", "review_decision", "draft", "unresolved_threads", "gtt_present", "stale", "exception", "repeat_failure")
    def render(selected, state_entries=None, state_history=None, omitted=0, closed=False):
        selected = sorted(selected, key=lambda e: e["number"])
        state_entries = state_entries or []
        state_history = state_history or {}
        payload = {"schema": 2, "last_run_at": stamp, "entries": state_entries, "history": state_history}
        if omitted:
            payload["truncated"], payload["omitted"] = True, omitted
        lines = [SUMMARY, STATE + state_json(payload) + "\n-->\n# Open stuck PRs\n", f"last_run_at: {stamp}\n", "Legend: am=auto-merge, m=mergeable, rv=review, d=Draft, u=unresolved, g=GTT, st=stale, ex=auto-merge-exempt.\n"]
        def visible(value): return quoted(value)
        def label(value, fallback="unknown"):
            return visible(fallback if value is None else value)
        state_keys = {entry["number"] for entry in state_entries}
        rows = []
        reason_codes = {
            "required checks failed": "checks",
            "auto-merge is not enabled": "auto-merge",
            "merge conflict": "conflict",
            "changes requested": "review",
            "branch is behind main": "behind",
            "stale": "stale",
            "Draft open too long": "draft-age",
            "open for": "open-age",
            "unresolved discussion": "threads",
            "manual review requested": "review-request",
            "owner-review label remains": "owner-review",
            "merge state unknown": "unknown-merge",
        }
        def compact_reasons(values):
            compact = []
            for reason in values:
                code = next((value for prefix, value in reason_codes.items() if reason.startswith(prefix)), quoted(reason))
                if code not in compact: compact.append(code)
            return ",".join(compact) or "none"
        for e in sorted(selected, key=lambda e: e["number"]):
            repeat = e["repeat_failure"] if e["number"] in state_keys else "unknown"
            rows.append(f"- #{e['number']}: {visible(e['classification'])}; why={compact_reasons(e['reasons'])}; age={e['age_hours']}h; repeat={'unknown' if repeat == 'unknown' else ('yes' if repeat else 'no')}; am={'on' if e['auto_merge'] else 'off'}, m={label(e['mergeable'])}, rv={label(e['review_decision'])}, d={'yes' if e['draft'] else 'no'}, u={e['unresolved_threads']}, g={'present' if e['gtt_present'] else 'absent'}, st={'yes' if e['stale'] else 'no'}, ex={'yes' if e['exception'] else 'no'}")
        lines += rows
        if omitted:
            lines.append(f"State coverage is truncated: {omitted} PR state record(s) omitted; recurrence for omitted entries is unknown and machine state is a lower bound.")
        if closed:
            lines.append("No open stuck PRs.")
        return "\n".join(lines) + "\n"
    # The visible list is complete. Only the machine state is budgeted, with
    # actionable/current rows taking priority over history-only records.
    entries = sorted(entries, key=lambda e: (e["classification"] != "actionable", e["number"], e["head"]))
    entry_payloads = [{key: entry.get(key) for key in state_fields} for entry in entries]
    entry_key = lambda e: f"{e['number']}:{e['head']}"
    history_keys = sorted(history, key=lambda key: (int(key.split(":", 1)[0]), key))
    selected_entries, selected_history = [], {}
    omitted = 0
    for entry in entry_payloads:
        if len(render([], [entry], {}).encode("utf-8")) >= 65536:
            raise ValueError("Single state record exceeds GitHub limit")
    for key in history_keys:
        if len(render([], [], {key: history[key]}).encode("utf-8")) >= 65536:
            raise ValueError("Single state record exceeds GitHub limit")
    for entry in entry_payloads:
        candidate = selected_entries + [entry]
        candidate_keys = {entry_key(e): e for e in candidate}
        candidate_history = {key: history[key] for key in sorted(candidate_keys) if key in history}
        test = render(entries, candidate, candidate_history, len(entry_payloads) - len(candidate))
        if len(test.encode("utf-8")) >= 65536:
            omitted = len(entry_payloads) - len(selected_entries)
            break
        selected_entries = candidate
        selected_history = candidate_history
    else:
        for key in history_keys:
            if key in selected_history: continue
            candidate_history = dict(selected_history); candidate_history[key] = history[key]
            test = render(entries, selected_entries, {k: candidate_history[k] for k in sorted(candidate_history)}, 0)
            if len(test.encode("utf-8")) >= 65536:
                omitted = len(history_keys) - len(selected_history)
                break
            selected_history = candidate_history
    if omitted:
        # omitted counts all records not represented in machine state; rows
        # are still complete and are deliberately rendered with repeat=unknown.
        represented = {e["number"] for e in selected_entries}
        omitted = len(entry_payloads) - len(represented) + max(0, len(history) - len(selected_history))
    body = render(entries, selected_entries, {k: selected_history[k] for k in sorted(selected_history)}, omitted, closed=not entries)
    if len(body.encode("utf-8")) >= 65536:
        raise ValueError("Summary body exceeds GitHub limit")
    # Validate every pending comment before the first write.
    if any(len(comment.encode("utf-8")) >= 65536 for _, comment in pending_comments):
        raise ValueError("Comment exceeds GitHub limit")
    assignee = {"assignees": [options["summary_assignee"]]} if options["summary_assignee"] else {}
    desired_state = "open" if entries else "closed"
    if summary:
        update = {"state": desired_state, "body": body, **assignee}
        if summary.get("state") != desired_state or summary.get("body") != body or assignee:
            api.rest("PATCH", f"issues/{summary['number']}", update)
    elif entries:
        api.rest("POST", "issues", {"title": TITLE, "body": body, **assignee})
    for number, comment in pending_comments:
        api.rest("POST", f"issues/{number}/comments", {"body": comment})
    print(f"[stuck-pr-bot] scanned open PRs; {len(entries)} summary entries; {len(actionable)} actionable")


def main():
    try:
        run(API(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]), dt.datetime.now(dt.timezone.utc), failure_hours=os.environ.get("FAILURE_HOURS") or 2, open_hours=os.environ.get("OPEN_HOURS") or 24, stale_days=os.environ.get("STALE_DAYS") or 14, draft_days=os.environ.get("DRAFT_DAYS") or 7, auto_merge_grace_minutes=os.environ.get("AUTO_MERGE_GRACE_MINUTES") or 30, thread_hours=os.environ.get("THREAD_HOURS") or 24, mention_allowlist=os.environ.get("MENTION_ALLOWLIST", ""), summary_assignee=os.environ.get("SUMMARY_ASSIGNEE", ""), exclude_prs=os.environ.get("EXCLUDE_PRS", ""), auto_merge_exempt_prs=os.environ.get("AUTO_MERGE_EXEMPT_PRS", ""))
    except (ValueError, KeyError, IndexError, TypeError, OSError, urllib.error.URLError):
        print("stuck-pr-bot: API/configuration data unavailable; reporting run failed.", file=sys.stderr); return 1
    return 0


if __name__ == "__main__": sys.exit(main())
