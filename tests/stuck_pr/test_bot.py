"""Offline behavior and API pagination tests; no GitHub writes or PR code."""
import copy
import datetime as dt
import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stuck_pr_bot", ROOT / "scripts/stuck_pr/bot.py")
bot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bot)
NOW = dt.datetime(2026, 10, 20, 12, tzinfo=dt.timezone.utc)
HEAD = "a" * 40


def ago(hours):
    return (NOW - dt.timedelta(hours=hours)).isoformat()


def check(name="quality / aggregate", required=True, conclusion="FAILURE", attempt=1, app=1, completed=3):
    return {"name": name, "isRequired": required, "conclusion": conclusion,
            "status": "COMPLETED", "completedAt": ago(completed), "databaseId": attempt,
            "checkSuite": {"app": {"databaseId": app}}}


def pr(*, age=4, quiet=3, contexts=None, head=HEAD, draft=False, state="OPEN"):
    return {"state": state, "isDraft": draft, "headRefOid": head,
            "createdAt": ago(age), "updatedAt": ago(quiet),
            "commits": {"nodes": [{"commit": {"oid": head, "statusCheckRollup": None}}]},
            "contexts": [check()] if contexts is None else contexts}


def item(body, number=99, state="open", login=bot.BOT):
    return {"body": body, "number": number, "state": state, "title": bot.TITLE,
            "user": {"type": "Bot", "login": login}}


class FakeAPI:
    def __init__(self, prs=None, issues=None, comments=None):
        self.prs = {1: pr()} if prs is None else prs
        self.issues = [] if issues is None else issues
        self.comments = {} if comments is None else comments
        self.writes, self.reads = [], []
        self.refresh = {}

    def pages(self, suffix):
        self.reads.append(suffix)
        if suffix == "pulls?state=open":
            return iter({"number": n, "draft": p["isDraft"]} for n, p in self.prs.items())
        if suffix.startswith("issues?state=all"):
            return iter(self.issues)
        number = int(suffix.split("/")[1])
        return iter(self.comments.get(number, []))

    def snapshot(self, number):
        self.reads.append(("snapshot", number))
        result = copy.deepcopy(self.prs[number])
        if number in self.refresh:
            self.prs[number] = self.refresh.pop(number)
        return result

    def rest(self, method, suffix, body=None):
        self.writes.append((method, suffix, body))
        if suffix.endswith("/comments"):
            number = int(suffix.split("/")[1])
            self.comments.setdefault(number, []).append(item(body["body"]))
        elif suffix == "issues":
            self.issues.append(item(body["body"]))
        else:
            for issue in self.issues:
                if suffix == f"issues/{issue['number']}":
                    issue.update(body)
        return {}


class DecisionTests(unittest.TestCase):
    def test_failed_required_check_waits_two_hours(self):
        self.assertIsNone(bot.report(pr(contexts=[check(completed=1.99)]), NOW, 2, 24))
        text = bot.report(pr(contexts=[check(completed=2)]), NOW, 2, 24)
        self.assertIn(HEAD, text)
        self.assertIn("quality / aggregate", text)
        self.assertIn("2.0 hours", text)
        self.assertIn("Bot 不会修", text)

    def test_recent_comment_does_not_reset_three_hour_old_failure(self):
        text = bot.report(pr(quiet=0.5, contexts=[check(completed=3)]), NOW, 2, 24)
        self.assertIsNotNone(text)
        self.assertIn("3.0 hours ago", text)
        self.assertIn(ago(3), text)
        self.assertNotIn("Push inactivity", text)

    def test_earliest_current_required_failure_controls_threshold(self):
        contexts = [check(name="new failure", completed=0.5), check(name="old failure", completed=3),
                    check(name="optional", required=False, completed=10)]
        names, completed = bot.failures(contexts)
        self.assertEqual(["new failure", "old failure"], names)
        self.assertEqual(NOW - dt.timedelta(hours=3), completed)
        self.assertIsNotNone(bot.report(pr(quiet=0, contexts=contexts), NOW, 2, 24))
        self.assertIsNone(bot.report(pr(contexts=contexts[:1] + contexts[2:]), NOW, 2, 24))

    def test_new_head_restarts_failure_clock_even_with_old_report(self):
        marker = f"<!-- stuck-pr-bot:v1 head={HEAD} -->"
        api = FakeAPI(prs={1: pr(head="b" * 40, contexts=[check(completed=0.5)])},
                      comments={1: [item(marker)]}, issues=[item(bot.SUMMARY)])
        bot.run(api, NOW)
        self.assertEqual([("PATCH", "issues/99")], [(m, p) for m, p, _ in api.writes])
        self.assertEqual("closed", api.issues[0]["state"])

    def test_missing_failure_completion_fails_without_writes(self):
        context = check()
        context["completedAt"] = None
        api = FakeAPI(prs={1: pr(contexts=[context])})
        with self.assertRaises(ValueError):
            bot.run(api, NOW)
        self.assertEqual([], api.writes)

    def test_optional_failure_pending_skipped_neutral_and_success_are_healthy(self):
        for conclusion in ("SUCCESS", "NEUTRAL", "SKIPPED", None):
            self.assertIsNone(bot.report(pr(contexts=[check(conclusion=conclusion)]), NOW, 2, 24))
        self.assertIsNone(bot.report(pr(contexts=[check(required=False)]), NOW, 2, 24))
        pending = check()
        pending["status"] = "IN_PROGRESS"
        self.assertIsNone(bot.report(pr(contexts=[pending]), NOW, 2, 24))

    def test_latest_attempt_and_app_identity(self):
        contexts = [check(attempt=1), check(attempt=2, conclusion="SUCCESS")]
        self.assertEqual(([], None), bot.failures(contexts))
        contexts.append(check(app=2))
        self.assertEqual(["quality / aggregate"], bot.failures(contexts)[0])
        self.assertEqual(([], None), bot.failures(list(reversed(contexts[:2]))))
        # A rerun's current failed attempt supplies its own completion time.
        self.assertIsNone(bot.report(pr(contexts=[check(attempt=1, completed=8),
                                                 check(attempt=2, completed=0.5)]), NOW, 2, 24))

    def test_legacy_status_contexts_latest_wins(self):
        old = {"context": "legacy", "state": "FAILURE", "createdAt": ago(4), "isRequired": True}
        new = dict(old, state="SUCCESS", createdAt=ago(1))
        self.assertEqual((["legacy"], NOW - dt.timedelta(hours=4)), bot.failures([old]))
        self.assertEqual(([], None), bot.failures([new, old]))
        self.assertIsNotNone(bot.report(pr(quiet=0, contexts=[old]), NOW, 2, 24))

    def test_age_threshold_reports_without_failure_or_recent_activity(self):
        self.assertIsNone(bot.report(pr(age=24, quiet=0, contexts=[]), NOW, 2, 24))
        text = bot.report(pr(age=24.01, quiet=0, contexts=[]), NOW, 2, 24)
        self.assertIn("none observed", text)
        self.assertIn("without merging", text)

    def test_drafts_closed_and_merged_are_ignored(self):
        for data in (pr(age=48, draft=True), pr(age=48, state="CLOSED"), pr(age=48, state="MERGED")):
            self.assertIsNone(bot.report(data, NOW, 2, 24))

    def test_wrong_head_check_identity_rejected(self):
        data = pr()
        data["commits"]["nodes"][0]["commit"]["oid"] = "b" * 40
        with self.assertRaises(ValueError):
            bot.report(data, NOW, 2, 24)

    def test_untrusted_check_name_is_quoted_and_cannot_ping(self):
        text = bot.report(pr(contexts=[check(name="@all\n[x](https://example.invalid) <script>")]), NOW, 2, 24)
        self.assertNotIn("@all", text)
        self.assertIn(r"\[x\]\(https://example.invalid\)", text)
        self.assertNotIn("<script>", text)

    def test_large_failure_list_respects_comment_body_limit(self):
        checks = [check(name=str(i) + "[" * 300) for i in range(300)]
        text = bot.report(pr(contexts=checks), NOW, 2, 24)
        self.assertLess(len(text), 65536)
        self.assertIn("more failed required checks", text)

    def test_custom_thresholds_and_invalid_values(self):
        self.assertIsNone(bot.report(pr(contexts=[check(completed=3)]), NOW, 4, 48))
        self.assertIsNotNone(bot.report(pr(contexts=[check(completed=1)]), NOW, 0.5, 48))
        for value in (0, -1, "nan", "inf", "bad"):
            api = FakeAPI()
            with self.assertRaises(ValueError):
                bot.run(api, NOW, value, 24)
            self.assertEqual([], api.writes + api.reads)


class ReconciliationTests(unittest.TestCase):
    def test_report_once_per_head_and_update_issue(self):
        api = FakeAPI()
        bot.run(api, NOW)
        self.assertEqual([("POST", "issues/1/comments"), ("POST", "issues")], [(m, p) for m, p, _ in api.writes])
        api.writes.clear()
        bot.run(api, NOW)
        self.assertEqual([], api.writes)
        api.prs[1] = pr(head="b" * 40)
        bot.run(api, NOW)
        self.assertEqual([("POST", "issues/1/comments")], [(m, p) for m, p, _ in api.writes])
        api.writes.clear()
        api.prs[2] = pr()
        bot.run(api, NOW)
        self.assertEqual([("POST", "issues/2/comments"), ("PATCH", "issues/99")], [(m, p) for m, p, _ in api.writes])

    def test_only_owned_marker_can_suppress_comment_or_select_summary(self):
        marker = f"<!-- stuck-pr-bot:v1 head={HEAD} -->"
        api = FakeAPI(issues=[item(bot.SUMMARY, login="someone")],
                      comments={1: [item(marker, login="someone")]})
        bot.run(api, NOW)
        self.assertEqual(["issues/1/comments", "issues"], [p for _, p, _ in api.writes])

    def test_summary_lists_all_stuck_prs_only(self):
        api = FakeAPI(prs={1: pr(), 2: pr(age=48, quiet=0, contexts=[]),
                          3: pr(contexts=[]), 4: pr(age=48, draft=True)})
        bot.run(api, NOW)
        body = api.writes[-1][2]["body"]
        self.assertIn("- #1", body)
        self.assertIn("- #2", body)
        self.assertNotIn("- #3", body)
        self.assertNotIn("- #4", body)
        self.assertNotIn(("snapshot", 4), api.reads)

    def test_healthy_repository_has_no_writes_and_closes_existing_issue(self):
        api = FakeAPI(prs={1: pr(contexts=[])})
        bot.run(api, NOW)
        self.assertEqual([], api.writes)
        api.issues = [item(bot.SUMMARY)]
        bot.run(api, NOW)
        self.assertEqual("closed", api.writes[-1][2]["state"])
        api.writes.clear()
        bot.run(api, NOW)
        self.assertEqual([], api.writes)

    def test_summary_reopened_without_duplicate_issue(self):
        api = FakeAPI(issues=[item(bot.SUMMARY, state="closed")])
        bot.run(api, NOW)
        self.assertEqual(("PATCH", "issues/99"), api.writes[-1][:2])
        self.assertEqual("open", api.writes[-1][2]["state"])

    def test_bot_comment_and_later_activity_cannot_hide_known_failed_head(self):
        api = FakeAPI()
        bot.run(api, NOW)
        api.prs[1]["updatedAt"] = NOW.isoformat()
        api.writes.clear()
        bot.run(api, NOW + dt.timedelta(hours=1))
        self.assertEqual([], api.writes)
        self.assertEqual("open", api.issues[0]["state"])
        # Recovery still clears the summary, regardless of the old marker.
        api.prs[1]["contexts"] = []
        bot.run(api, NOW + dt.timedelta(hours=1))
        self.assertEqual("closed", api.issues[0]["state"])

    def test_summary_keeps_hundreds_of_reports_within_issue_body_limit(self):
        api = FakeAPI(prs={i: pr() for i in range(1, 501)})
        bot.run(api, NOW)
        body = api.writes[-1][2]["body"]
        self.assertIn("- #500", body)
        self.assertLess(len(body), 65536)

    def test_head_race_closed_draft_or_recovered_before_write(self):
        for refreshed in (pr(head="b" * 40), pr(state="MERGED"), pr(draft=True), pr(contexts=[])):
            api = FakeAPI()
            api.refresh[1] = refreshed
            bot.run(api, NOW)
            self.assertEqual([], api.writes)

    def test_read_failure_does_not_publish_partial_summary(self):
        api = FakeAPI(prs={1: pr(), 2: pr()})
        original = api.snapshot
        def snapshot(number):
            if number == 2:
                raise ValueError("unavailable")
            return original(number)
        api.snapshot = snapshot
        with self.assertRaises(ValueError):
            bot.run(api, NOW)
        self.assertEqual([], api.writes)


class PaginationTests(unittest.TestCase):
    def test_rest_pagination_reads_beyond_first_hundred(self):
        api = bot.API("org/repo", "fixture")
        requests = []
        def rest(method, suffix, body=None):
            requests.append((method, suffix))
            return [{}] * 100 if suffix.endswith("&page=1") else [{"last": True}]
        api.rest = rest
        self.assertEqual(101, len(list(api.pages("pulls?state=open"))))
        self.assertEqual(("GET", "pulls?state=open&per_page=100&page=2"), requests[-1])

    def test_graphql_paginates_exact_head_required_contexts(self):
        api = bot.API("org/repo", "fixture")
        requests = []
        def request(method, path, body):
            requests.append((method, path, body))
            first = body["variables"]["cursor"] is None
            data = pr()
            data.pop("contexts")
            data["commits"]["nodes"][0]["commit"]["statusCheckRollup"] = {"contexts": {
                "nodes": [check(required=False)] if first else [check(name="required")],
                "pageInfo": {"hasNextPage": first, "endCursor": "next"}}}
            return {"data": {"repository": {"pullRequest": data}}}
        api.request = request
        data = api.snapshot(7)
        self.assertEqual(["required"], bot.failures(data["contexts"])[0])
        self.assertEqual("next", requests[1][2]["variables"]["cursor"])
        self.assertIn("isRequired(pullRequestNumber:$number)", requests[0][2]["query"])
        self.assertIn("commits(last:1)", requests[0][2]["query"])
        self.assertIn("completedAt", requests[0][2]["query"])
        self.assertNotIn("updatedAt", requests[0][2]["query"])

    def test_graphql_error_fails_instead_of_treating_as_healthy(self):
        api = bot.API("org/repo", "fixture")
        api.request = lambda *args: {"errors": [{"message": "denied"}]}
        with self.assertRaises(ValueError):
            api.snapshot(7)


if __name__ == "__main__":
    unittest.main()
