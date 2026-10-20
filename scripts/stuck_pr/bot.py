#!/usr/bin/env python3
"""Report stuck PRs; no repair, check rerun, approval or merge operations."""
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
BOT = "github-actions[bot]"
FAILED = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE"}
QUERY = """
query($owner:String!, $repo:String!, $number:Int!, $cursor:String) {
  repository(owner:$owner, name:$repo) {
    pullRequest(number:$number) {
      state isDraft headRefOid createdAt
      commits(last:1) { nodes { commit {
        oid
        statusCheckRollup { contexts(first:100, after:$cursor) {
          pageInfo { hasNextPage endCursor }
          nodes {
            ... on CheckRun {
              name databaseId conclusion status completedAt
              isRequired(pullRequestNumber:$number)
              checkSuite { app { databaseId } }
            }
            ... on StatusContext {
              context state createdAt isRequired(pullRequestNumber:$number)
            }
          }
        } }
      } } }
    }
  }
}
"""


def instant(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp unavailable")
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp has no timezone")
    return result


def threshold(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("Thresholds must be finite positive hours")
    return result


def quoted(value):
    # Check names are untrusted data, including mentions, Markdown and newlines.
    value = " ".join(value.split())[:300].replace("@", "＠")
    return re.sub(r"([\\`*_{}\[\]()<>!|])", r"\\\1", value)


def failures(contexts):
    """Return current failed required names and their earliest completion time."""
    latest = {}
    for item in contexts:
        if "name" in item:
            app = (item["checkSuite"].get("app") or {}).get("databaseId")
            key, rank = ("check", item["name"], app), item["databaseId"]
            name = item["name"]
            failed = item["status"] == "COMPLETED" and item["conclusion"] in FAILED
            completed = item.get("completedAt")
        else:
            key, rank = ("status", item["context"]), instant(item["createdAt"])
            name, failed = item["context"], item["state"] in {"ERROR", "FAILURE"}
            completed = item["createdAt"]
        if key not in latest or rank > latest[key][0]:
            latest[key] = (rank, name, item["isRequired"], failed, completed)
    current = [(name, instant(completed)) for _, name, required, failed, completed in latest.values()
               if required and failed]
    return sorted({name for name, _ in current}), min((completed for _, completed in current), default=None)


def report(pr, now, failure_hours, open_hours):
    if pr["state"] != "OPEN" or pr["isDraft"]:
        return None
    head = pr["headRefOid"]
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("Invalid head identity")
    commit = pr["commits"]["nodes"][-1]["commit"]
    if commit["oid"] != head:
        raise ValueError("Head and check commit differ")
    age = (now - instant(pr["createdAt"])).total_seconds() / 3600
    failed, completed = failures(pr["contexts"])
    elapsed = (now - completed).total_seconds() / 3600 if completed is not None else None
    reasons = []
    if elapsed is not None and elapsed >= failure_hours:
        reasons.append(f"Required checks failed; earliest failed check completed {elapsed:.1f} hours ago (threshold {failure_hours:g}).")
    if age > open_hours:
        reasons.append(f"Open for {age:.1f} hours (threshold {open_hours:g}) without merging.")
    if not reasons:
        return None
    rendered, used = [], 0
    for name in failed:
        safe = quoted(name)
        if used + len(safe) + 2 > 50000:
            break
        rendered.append(safe)
        used += len(safe) + 2
    names = ", ".join(rendered) or "none observed"
    if len(rendered) < len(failed):
        names += f"; {len(failed) - len(rendered)} more failed required checks (see this PR's checks tab)"
    return (f"<!-- stuck-pr-bot:v1 head={head} -->\n"
            f"## Stuck PR report\n\nHead: `{head}`\n\n" + "\n".join(reasons) +
            f"\n\nFailed required checks: {names}.\n\n" +
            (f"Earliest failed required check completed at `{completed.isoformat()}` ({elapsed:.1f} hours ago). " if completed is not None else "") +
            f"PR age: {age:.1f} hours.\n\nBot 不会修 (the bot will not repair). "
            "This bot only reports; it never reruns checks, approves or merges.\n")


class API:
    def __init__(self, repository, token):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository")
        self.repository, self.token = repository, token

    def request(self, method, path, body=None):
        graphql = path == "graphql"
        base = os.environ.get("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql") if graphql else os.environ.get("GITHUB_API_URL", "https://api.github.com") + "/"
        url = base if graphql else base + path
        request = urllib.request.Request(url, method=method,
            data=None if body is None else json.dumps(body).encode(), headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
        # Do not redirect a credential-bearing request to another host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            return json.load(response)

    def rest(self, method, suffix, body=None):
        return self.request(method, "repos/" + self.repository + "/" + suffix, body)

    def pages(self, suffix):
        page = 1
        while True:
            rows = self.rest("GET", suffix + ("&" if "?" in suffix else "?") + f"per_page=100&page={page}")
            if not isinstance(rows, list):
                raise ValueError("Invalid paginated response")
            yield from rows
            if len(rows) < 100:
                break
            page += 1

    def snapshot(self, number):
        owner, repo = self.repository.split("/")
        cursor, contexts, identity = None, [], None
        while True:
            data = self.request("POST", "graphql", {"query": QUERY, "variables": {
                "owner": owner, "repo": repo, "number": number, "cursor": cursor}})
            if data.get("errors"):
                raise ValueError("GitHub check/required-status query failed")
            pr = data["data"]["repository"]["pullRequest"]
            if pr is None:
                raise ValueError("PR unavailable")
            if pr["state"] != "OPEN" or pr["isDraft"]:
                return pr
            if identity is None:
                identity = pr["headRefOid"]
            elif identity != pr["headRefOid"]:
                raise ValueError("Head changed during check pagination; try the next scheduled run")
            commit = pr["commits"]["nodes"][-1]["commit"]
            rollup = commit["statusCheckRollup"]
            if rollup is None:
                break
            connection = rollup["contexts"]
            contexts.extend(connection["nodes"])
            info = connection["pageInfo"]
            if not info["hasNextPage"]:
                break
            after = info["endCursor"]
            if not after or after == cursor:
                raise ValueError("Invalid check pagination cursor")
            cursor = after
        pr["contexts"] = contexts
        return pr


def owned(item, marker):
    return (item.get("user", {}).get("login") == BOT and
            item.get("user", {}).get("type") == "Bot" and
            (item.get("body") or "").startswith(marker))


def run(api, now, failure_hours=2, open_hours=24):
    failure_hours, open_hours = threshold(failure_hours), threshold(open_hours)
    stuck = []
    # Complete the read phase before writing anything; API errors fail the run.
    for item in api.pages("pulls?state=open"):
        if item["draft"]:
            continue
        number = item["number"]
        pr = api.snapshot(number)
        body = report(pr, now, failure_hours, open_hours)
        if body:
            stuck.append((number, pr["headRefOid"]))
    summaries = [item for item in api.pages("issues?state=all&creator=" + BOT)
                 if "pull_request" not in item and owned(item, SUMMARY) and item["title"] == TITLE]
    current = []
    for number, head in stuck:
        # Re-read exact head and checks immediately before publication.
        pr = api.snapshot(number)
        body = report(pr, now, failure_hours, open_hours)
        if not body or pr["headRefOid"] != head:
            continue
        marker = f"<!-- stuck-pr-bot:v1 head={head} -->"
        comments = list(api.pages(f"issues/{number}/comments"))
        if not any(owned(comment, marker) for comment in comments):
            api.rest("POST", f"issues/{number}/comments", {"body": body})
        current.append(number)
    summary = min(summaries, key=lambda item: item["number"]) if summaries else None
    if current:
        body = (SUMMARY + "\n# Open stuck PRs\n\n"
                "Check and wait details are in each PR's bot report.\n\n" +
                "\n".join(f"- #{number}" for number in current))
        if summary is None:
            api.rest("POST", "issues", {"title": TITLE, "body": body})
        elif summary["state"] != "open" or summary["body"] != body:
            api.rest("PATCH", f"issues/{summary['number']}", {"state": "open", "body": body})
    elif summary is not None and summary["state"] == "open":
        api.rest("PATCH", f"issues/{summary['number']}", {"state": "closed", "body": SUMMARY + "\nNo open stuck PRs.\n"})
    print(f"[stuck-pr-bot] scanned open PRs; {len(current)} stuck")


def main():
    try:
        run(API(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]),
            dt.datetime.now(dt.timezone.utc), os.environ.get("FAILURE_HOURS") or "2",
            os.environ.get("OPEN_HOURS") or "24")
    except (ValueError, KeyError, IndexError, TypeError, OSError, urllib.error.URLError):
        print("stuck-pr-bot: API/configuration data unavailable; reporting run failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
