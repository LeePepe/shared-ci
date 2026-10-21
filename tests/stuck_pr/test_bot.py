"""Offline contract tests for report-only stuck-PR classification."""
import copy
import datetime as dt
import importlib.util
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stuck_pr_bot", ROOT / "scripts/stuck_pr/bot.py")
bot = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(bot)
NOW = dt.datetime(2026, 10, 20, 12, tzinfo=dt.timezone.utc)
HEAD = "a" * 40


def ago(hours): return (NOW - dt.timedelta(hours=hours)).isoformat()


def check(name="quality / aggregate", required=True, conclusion="FAILURE", attempt=1, app=1, completed=3):
    return {"name": name, "isRequired": required, "conclusion": conclusion, "status": "COMPLETED",
            "completedAt": ago(completed), "databaseId": attempt, "checkSuite": {"app": {"databaseId": app}}}


def pr(*, age=4, contexts=None, head=HEAD, draft=False, state="OPEN", **extra):
    data = {"state": state, "isDraft": draft, "headRefOid": head, "createdAt": ago(age),
            "commits": {"nodes": [{"commit": {"oid": head}}]}, "contexts": contexts or [],
            "autoMergeRequest": {"enabledAt": ago(1)}, "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN", "reviewDecision": "APPROVED", "author": {"login": "alice"}}
    data.update(extra); return data


def item(body, number=99, state="open", login=bot.BOT, created_at=None):
    return {"body": body, "number": number, "state": state, "title": bot.TITLE,
            **({"created_at": created_at} if created_at else {}),
            "user": {"type": "Bot", "login": login}}


def state_item(state, number=99, status="open"):
    body = bot.SUMMARY + "\n" + bot.STATE + bot.state_json(state) + "\n-->\n"
    return item(body, number=number, state=status)


class FakeAPI:
    def __init__(self, prs=None, issues=None, comments=None):
        self.prs = {1: pr(contexts=[check()])} if prs is None else prs
        self.issues = [] if issues is None else issues; self.comments = {} if comments is None else comments
        self.next_issue = max((issue["number"] for issue in self.issues), default=98) + 1
        self.writes, self.reads, self.refresh = [], [], {}

    def pages(self, suffix):
        self.reads.append(suffix)
        if suffix == "pulls?state=open": return iter({"number": n, "draft": p["isDraft"]} for n, p in self.prs.items())
        if suffix.startswith("issues?state=all"): return iter(self.issues)
        return iter(self.comments.get(int(suffix.split("/")[1]), []))

    def snapshot(self, number):
        self.reads.append(("snapshot", number))
        if number in self.refresh:
            current = copy.deepcopy(self.prs[number])
            self.prs[number] = self.refresh.pop(number)
            return current
        return copy.deepcopy(self.prs[number])

    def rest(self, method, suffix, body=None):
        self.writes.append((method, suffix, body))
        if suffix.endswith("/comments"):
            self.comments.setdefault(int(suffix.split("/")[1]), []).append(item(body["body"]))
        elif suffix == "issues":
            number = self.next_issue; self.next_issue += 1
            created_at = (dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=number)).isoformat().replace("+00:00", "Z")
            self.issues.append(item(body["body"], number=number, created_at=created_at))
        elif suffix.startswith("issues/"):
            number = int(suffix.split("/")[1])
            for issue in self.issues:
                if issue["number"] == number: issue.update(body)
        return {}


class ClassificationTests(unittest.TestCase):
    def test_required_failure_threshold_and_exact_head(self):
        self.assertIsNone(bot.report(pr(contexts=[check(completed=1.99)]), NOW, 2, 24))
        text = bot.report(pr(contexts=[check(completed=2)]), NOW, 2, 24)
        self.assertIn("required checks failed", text); self.assertIn("Bot 不会修", text)
        bad = pr(); bad["commits"]["nodes"][0]["commit"]["oid"] = "b" * 40
        with self.assertRaises(ValueError): bot.report(bad, NOW, 2, 24)

    def test_earliest_current_required_failure_controls_threshold(self):
        contexts = [check(name="new failure", completed=.5), check(name="old failure", completed=3),
                    check(name="optional", required=False, completed=10)]
        names, completed = bot.failures(contexts)
        self.assertEqual(["new failure", "old failure"], names)
        self.assertEqual(NOW - dt.timedelta(hours=3), completed)
        self.assertIsNotNone(bot.report(pr(contexts=contexts), NOW, 2, 24))
        self.assertIsNone(bot.report(pr(contexts=contexts[:1] + contexts[2:]), NOW, 2, 24))

    def test_latest_legacy_status_context_controls_failure_clock(self):
        old = {"context": "legacy", "state": "FAILURE", "createdAt": ago(4), "isRequired": True}
        new = dict(old, state="SUCCESS", createdAt=ago(1))
        self.assertEqual((["legacy"], NOW - dt.timedelta(hours=4)), bot.failures([old]))
        self.assertEqual(([], None), bot.failures([new, old]))

    def test_new_head_restarts_failure_clock(self):
        old = pr(head=HEAD, contexts=[check(completed=3)])
        new = pr(head="b" * 40, contexts=[check(completed=.5)])
        self.assertIsNotNone(bot.report(old, NOW, 2, 24))
        self.assertIsNone(bot.report(new, NOW, 2, 24))

    def test_recent_activity_does_not_reset_failure_clock(self):
        data = pr(updatedAt=NOW.isoformat(), quiet=0, contexts=[check(completed=3)])
        text = bot.report(data, NOW, 2, 24)
        self.assertIsNotNone(text)
        self.assertIn("3.0h", text)

    def test_actionable_signals_and_age_is_context_only(self):
        options = bot.default_options()
        self.assertEqual("summary-only", bot.classify(pr(age=25), NOW, options)["classification"])
        for field, value in (("mergeable", "CONFLICTING"), ("mergeStateStatus", "BEHIND"), ("reviewDecision", "CHANGES_REQUESTED")):
            data = pr(autoMergeRequest={}); data[field] = value
            self.assertEqual("actionable", bot.classify(data, NOW, options)["classification"])

    def test_draft_and_stale_are_summary_only_even_with_failure(self):
        options = bot.default_options()
        for data in (pr(age=24 * 8, draft=True, contexts=[check()]), pr(age=24 * 15, contexts=[check()])):
            result = bot.classify(data, NOW, options)
            self.assertEqual("summary-only", result["classification"])

    def test_mentions_are_allowlisted_and_untrusted_check_names_neutralized(self):
        data = pr(contexts=[check(name="@all [x](https://example.invalid)")], author={"login": "alice"})
        text = bot.report(data, NOW, 2, 24)
        self.assertNotIn("@all", text); self.assertIn(r"\[x\]\(https://example.invalid\)", text)
        self.assertNotIn("@alice", text)

    def test_exclusion_skips_snapshot_and_summary(self):
        api = FakeAPI(prs={1: pr(contexts=[check()]), 2: pr(contexts=[check()])})
        bot.run(api, NOW, exclude_prs="2")
        self.assertNotIn(("snapshot", 2), api.reads)
        self.assertNotIn("#2", api.writes[-1][2]["body"])

    def test_only_excluded_pr_has_no_detail_request_or_write(self):
        api = FakeAPI(prs={2: pr(contexts=[check()])})
        bot.run(api, NOW, exclude_prs="2")
        self.assertEqual([], api.writes)
        self.assertNotIn(("snapshot", 2), api.reads)

    def test_api_failure_does_not_publish_partial_result(self):
        api = FakeAPI(prs={1: pr(contexts=[check()]), 2: pr(contexts=[check()])})
        original = api.snapshot
        def failing(number):
            if number == 2: raise ValueError("unavailable")
            return original(number)
        api.snapshot = failing
        with self.assertRaises(ValueError): bot.run(api, NOW)
        self.assertEqual([], api.writes)


class ReconciliationTests(unittest.TestCase):
    def test_summary_state_and_visible_rows_neutralize_untrusted_text(self):
        evil = "bad --> @all [link](https://example.invalid)"
        api = FakeAPI(prs={1: pr(contexts=[check(name=evil)])})
        bot.run(api, NOW)
        body = next(payload["body"] for _, path, payload in api.writes if path == "issues")
        state = body.split(bot.STATE, 1)[1].split("\n-->", 1)[0]
        self.assertNotIn("-->", state)
        self.assertNotIn("@all", body)
        self.assertNotIn(evil, body)

    def test_closed_and_merged_prs_never_enter_summary_or_comments(self):
        api = FakeAPI(prs={1: pr(state="CLOSED", contexts=[check()]), 2: pr(state="MERGED", contexts=[check()])})
        bot.run(api, NOW)
        self.assertEqual([], api.writes)

    def test_allowlisted_author_is_mentioned(self):
        api = FakeAPI()
        bot.run(api, NOW, mention_allowlist="alice")
        self.assertIn("@alice", api.writes[-1][2]["body"])

    def test_actionable_comment_once_and_summary_contains_state_and_last_run(self):
        api = FakeAPI()
        bot.run(api, NOW)
        self.assertEqual(["POST", "POST"], [item[0] for item in api.writes])
        body = next(payload["body"] for method, path, payload in api.writes if path == "issues")
        self.assertIn("stuck-pr-bot:state:v2", body); self.assertIn("last_run_at: 2026-10-20T12:00:00Z", body)
        api.writes.clear(); bot.run(api, NOW)
        self.assertEqual([], api.writes)

    def test_first_actionable_report_is_not_suppressed_by_unpublished_recurrence(self):
        api = FakeAPI(prs={1: pr(age=25, contexts=[check(attempt=1, completed=1)])})
        bot.run(api, NOW)
        self.assertEqual(0, sum(path.endswith("/comments") for _, path, _ in api.writes))
        api.writes.clear()
        api.prs[1]["contexts"] = [check(attempt=2, completed=2)]
        bot.run(api, NOW)
        self.assertEqual(1, sum(path.endswith("/comments") for _, path, _ in api.writes))
        self.assertIn('"repeat_failure":true', next(payload["body"] for _, path, payload in api.writes
                                                   if path.startswith("issues/") and not path.endswith("/comments")))
        api.writes.clear()
        bot.run(api, NOW)
        self.assertEqual([], api.writes)

    def test_summary_only_keeps_issue_open_without_pr_comment(self):
        api = FakeAPI(prs={1: pr(age=25)})
        bot.run(api, NOW)
        self.assertEqual(["POST"], [item[0] for item in api.writes])
        self.assertNotIn("/comments", api.writes[0][1])

    def test_large_check_list_is_bounded(self):
        text = bot.report(pr(contexts=[check(name=str(i) + "[" * 300) for i in range(300)]), NOW, 2, 24)
        self.assertLess(len(text), 65536); self.assertIn("more failed required checks", text)

    def test_summary_keeps_hundreds_of_reports_within_issue_body_limit(self):
        api = FakeAPI(prs={i: pr(contexts=[check()]) for i in range(1, 501)})
        bot.run(api, NOW)
        bodies = [payload["body"] for _, path, payload in api.writes if path == "issues"]
        self.assertEqual(1, len(bodies))
        self.assertIn("- #500", bodies[0])
        self.assertEqual(500, bodies[0].count("\n- #"))
        self.assertLess(len(bodies[0].encode("utf-8")), 65536)
        state = bot.read_state(api.issues[0])
        self.assertTrue(state.get("truncated"))
        self.assertGreater(state.get("omitted", 0), 0)
        self.assertLess(len(state["entries"]), 500)
        self.assertEqual(500, sum(path.endswith("/comments") for _, path, _ in api.writes))
        self.assertEqual(500 - len(state["entries"]), state["omitted"])
        self.assertTrue(all(set(entry) == {"number", "head", "classification", "reasons", "age_hours", "auto_merge", "mergeable", "merge_state", "review_decision", "draft", "unresolved_threads", "gtt_present", "stale", "exception", "repeat_failure"} for entry in state["entries"]))

    def test_summary_rows_keep_all_signal_labels_visible(self):
        api = FakeAPI(prs={1: pr(age=24 * 15, autoMergeRequest=None, mergeable="CONFLICTING",
                                 mergeStateStatus="DIRTY", reviewDecision="CHANGES_REQUESTED",
                                 draft=True, gtt_present=True)})
        bot.run(api, NOW)
        body = next(payload["body"] for _, path, payload in api.writes if path == "issues")
        self.assertIn("Legend: am=auto-merge, m=mergeable, rv=review, d=Draft, u=unresolved, g=GTT, st=stale, ex=auto-merge-exempt.", body)
        for label in ("am=off", "m=CONFLICTING", r"rv=CHANGES\_REQUESTED",
                      "d=yes", "u=0", "g=present", "st=yes", "ex=no"):
            self.assertIn(label, body)

    def test_read_state_rejects_multi_summary_state(self):
        entry = {"number": 1, "head": HEAD}
        base = {"schema": 2, "last_run_at": None, "entries": [entry], "history": {}}
        with self.assertRaises(ValueError):
            bot.read_state([state_item(base, 10), state_item(base, 11)])

    def test_single_oversized_history_record_fails_before_writes(self):
        history = {"1:" + HEAD: {"seen_failed": True, "last_required_state": "failed",
                                   "latest_failed_attempt_ids": ["1"],
                                   "recovery_seen_at": "x" * 70000, "recurrent": True}}
        state = {"schema": 2, "last_run_at": None, "entries": [], "history": history}
        api = FakeAPI(prs={1: pr(contexts=[check()])}, issues=[state_item(state)])
        with self.assertRaises(ValueError):
            bot.run(api, NOW)
        self.assertEqual([], api.writes)

    def test_truncated_metadata_must_be_consistent(self):
        for extra in ({"truncated": True}, {"omitted": 1}, {"truncated": True, "omitted": 0},
                      {"truncated": False, "omitted": 1}, {"truncated": "yes", "omitted": 1}):
            state = {"schema": 2, "last_run_at": None, "entries": [], "history": {}, **extra}
            with self.assertRaises(ValueError): bot.read_state(state_item(state))

    def test_single_summary_interruption_has_zero_partial_writes(self):
        class FailOnce(FakeAPI):
            def rest(self, method, suffix, body=None):
                if method == "POST" and suffix == "issues":
                    raise ValueError("simulated summary write failure")
                return super().rest(method, suffix, body)
        api = FailOnce(prs={1: pr(contexts=[check()])})
        with self.assertRaises(ValueError): bot.run(api, NOW)
        self.assertEqual([], api.writes)

    def test_single_summary_patch_failure_retries_without_duplicate_comment(self):
        api = FakeAPI()
        bot.run(api, NOW)
        api.writes.clear()
        original = api.rest
        failed = [False]
        def fail_patch(method, suffix, body=None):
            if method == "PATCH" and suffix == "issues/99" and not failed[0]:
                failed[0] = True
                raise ValueError("summary PATCH failed")
            return original(method, suffix, body)
        api.rest = fail_patch
        with self.assertRaises(ValueError): bot.run(api, NOW + dt.timedelta(hours=1))
        api.rest = original
        api.writes.clear()
        bot.run(api, NOW + dt.timedelta(hours=1))
        self.assertEqual(0, sum(path.endswith("/comments") for _, path, _ in api.writes))

    def test_omitted_head_reloaded_is_unknown_and_does_not_suppress_first_comment(self):
        state = {"schema": 2, "last_run_at": NOW.isoformat(), "entries": [], "history": {},
                 "truncated": True, "omitted": 1}
        api = FakeAPI(prs={1: pr(contexts=[check()])}, issues=[state_item(state)])
        bot.run(api, NOW)
        body = next(payload["body"] for _, path, payload in api.writes if path == "issues/99")
        self.assertIn('"repeat_failure":"unknown"', body)
        self.assertEqual(1, sum(path.endswith("/comments") for _, path, _ in api.writes))

    def test_failure_recovery_failure_during_refresh_uses_final_snapshot(self):
        api = FakeAPI()
        bot.run(api, NOW)
        api.writes.clear()
        api.refresh[1] = pr(contexts=[])
        bot.run(api, NOW + dt.timedelta(hours=1))
        state = bot.read_state(api.issues[0])
        self.assertEqual("success", state["history"]["1:" + HEAD]["last_required_state"])
        api.writes.clear()
        api.refresh[1] = pr(contexts=[check(attempt=1, completed=1)])
        bot.run(api, NOW + dt.timedelta(hours=2))
        self.assertIn('"repeat_failure":true', api.writes[-1][2]["body"])

    def test_truncated_rows_have_unknown_recurrence_and_old_shards_are_not_merged(self):
        first = FakeAPI(prs={i: pr(contexts=[check()]) for i in range(1, 501)})
        bot.run(first, NOW)
        first.writes.clear()
        bot.run(first, NOW)
        body = first.issues[0]["body"]
        self.assertIn('"truncated":true', body)
        self.assertIn("repeat=unknown", body)
        self.assertEqual(1, len(first.issues))

        old_shard = state_item({"schema": 2, "last_run_at": None,
                                "entries": [{"number": 999, "head": "b" * 40}], "history": {}},
                               number=1000)
        old_shard["created_at"] = "2026-10-21T00:00:00Z"
        canonical = state_item({"schema": 2, "last_run_at": None, "entries": [], "history": {}},
                               number=1001)
        canonical["created_at"] = "2026-10-20T00:00:00Z"
        api = FakeAPI(prs={1: pr(contexts=[check()])}, issues=[old_shard, canonical])
        bot.run(api, NOW)
        self.assertEqual(1, sum(path == "issues/1001" for _, path, _ in api.writes))
        self.assertFalse(any(path == "issues/1000" for _, path, _ in api.writes))

    def test_latest_attempt_app_and_optional_status_contexts(self):
        contexts = [check(attempt=1, app=1), check(attempt=2, app=1, conclusion="SUCCESS"), check(attempt=1, app=2)]
        self.assertEqual(["quality / aggregate"], bot.failures(contexts)[0])
        self.assertEqual(["1"], bot.failure_attempts(contexts))
        pending = check(); pending["status"] = "IN_PROGRESS"
        for value in ("SUCCESS", "NEUTRAL", "SKIPPED", None):
            self.assertIsNone(bot.report(pr(contexts=[check(conclusion=value)]), NOW, 2, 24))
        self.assertIsNone(bot.report(pr(contexts=[check(required=False)]), NOW, 2, 24))
        old = {"context": "legacy", "state": "FAILURE", "createdAt": ago(4), "isRequired": True}
        self.assertEqual(["legacy"], bot.failures([old])[0])

    def test_threshold_boundaries_grace_open_stale_and_draft(self):
        options = bot.default_options()
        options["auto_merge_grace_minutes"] = 30
        self.assertIsNone(bot.classify(pr(age=.5, autoMergeRequest={}), NOW, options))
        self.assertEqual("actionable", bot.classify(pr(age=.51, autoMergeRequest={}), NOW, options)["classification"])
        self.assertIsNotNone(bot.classify(pr(age=24.01), NOW, options))
        self.assertIsNone(bot.classify(pr(age=24), NOW, options))
        self.assertEqual("summary-only", bot.classify(pr(age=24 * 14.01), NOW, options)["classification"])
        self.assertEqual("summary-only", bot.classify(pr(age=24 * 7.01, draft=True, contexts=[check()]), NOW, options)["classification"])

    def test_exempt_auto_merge_and_behind_signals(self):
        options = bot.default_options(); options["auto_merge_exempt_prs"] = {7}
        data = pr(age=2, autoMergeRequest={}, mergeStateStatus="BEHIND", contexts=[check()]); data["number"] = 7
        result = bot.classify(data, NOW, options)
        self.assertEqual("actionable", result["classification"])
        self.assertTrue(result["exception"])
        self.assertIn("required checks failed", result["reasons"][0])

    def test_unknown_and_missing_thread_time_are_summary_visible(self):
        options = bot.default_options()
        data = pr(mergeable="UNKNOWN", mergeStateStatus="UNKNOWN", threads=[{"isResolved": False, "isOutdated": False, "comments": {"nodes": [{}]}}])
        result = bot.classify(data, NOW, options)
        self.assertEqual("summary-only", result["classification"])
        self.assertTrue(result["thread_unknown"])
        self.assertIn("unknown", " ".join(result["reasons"]))

    def test_review_requests_labels_and_gtt_are_safe_summary_fields(self):
        data = pr(reviewRequests=[{"login": "reviewer"}], labels_owner_review=True, gtt_present=True)
        result = bot.classify(data, NOW, bot.default_options())
        self.assertEqual("summary-only", result["classification"])
        self.assertTrue(result["gtt_present"])

    def test_thread_age_is_configurable_and_unresolved_outdated_is_ignored(self):
        data = pr(threads=[{"isResolved": False, "isOutdated": False, "comments": {"nodes": [{"createdAt": ago(25)}]}},
                         {"isResolved": True, "isOutdated": False, "comments": {"nodes": [{"createdAt": ago(25)}]}},
                         {"isResolved": False, "isOutdated": True, "comments": {"nodes": [{"createdAt": ago(25)}]}}])
        result = bot.classify(data, NOW, bot.default_options())
        self.assertEqual(1, result["unresolved_threads"])


    def test_head_race_reconciles_without_stale_comment_or_entry(self):
        for refreshed in (pr(head="b" * 40), pr(state="MERGED"), pr(draft=True), pr(contexts=[])):
            api = FakeAPI(); api.refresh[1] = refreshed
            bot.run(api, NOW)
            self.assertEqual([], api.writes)

    def test_closed_summary_reopens_and_legacy_v1_marker_dedupes(self):
        marker = f"<!-- stuck-pr-bot:v1 head={HEAD} -->"
        api = FakeAPI(issues=[item(bot.SUMMARY, state="closed")], comments={1: [item(marker)]})
        bot.run(api, NOW)
        self.assertEqual("open", api.writes[-1][2]["state"])
        self.assertFalse(any(path.endswith("/comments") for _, path, _ in api.writes))
        self.assertIn("repeat=unknown", api.writes[-1][2]["body"])

    def test_human_marker_and_summary_cannot_suppress_or_select(self):
        marker = f"<!-- stuck-pr-bot:v1 head={HEAD} -->"
        api = FakeAPI(issues=[item(bot.SUMMARY, login="someone")], comments={1: [item(marker, login="someone")]})
        bot.run(api, NOW)
        self.assertEqual(["POST", "POST"], [method for method, _, _ in api.writes])
        self.assertTrue(any(path.endswith("/comments") for _, path, _ in api.writes))

    def test_zero_entries_closes_and_observation_only_stays_open(self):
        api = FakeAPI(prs={1: pr(contexts=[])})
        bot.run(api, NOW)
        self.assertEqual([], api.writes)
        api.issues = [item(bot.SUMMARY)]
        bot.run(api, NOW)
        self.assertEqual("closed", api.writes[-1][2]["state"])
        api = FakeAPI(prs={1: pr(age=25)})
        bot.run(api, NOW)
        self.assertEqual(["POST"], [method for method, _, _ in api.writes])

    def test_state_v2_corruption_fails_before_any_write(self):
        corrupt = item(bot.SUMMARY); corrupt["body"] = bot.SUMMARY + "\n<!-- stuck-pr-bot:state:v2\nnot-json\n-->"
        api = FakeAPI(issues=[corrupt])
        with self.assertRaises(ValueError): bot.run(api, NOW)
        self.assertEqual([], api.writes)

    def test_invalid_configuration_fails_before_any_read_or_write(self):
        for key, value in (("failure_hours", "nan"), ("open_hours", 0), ("exclude_prs", "2,bad"),
                           ("auto_merge_exempt_prs", "-1"), ("mention_allowlist", "bad login"),
                           ("summary_assignee", "bad login")):
            api = FakeAPI()
            with self.assertRaises(ValueError): bot.run(api, NOW, **{key: value})
            self.assertEqual([], api.reads + api.writes, key)

    def test_fail_success_fail_tracks_repeat_and_suppresses_second_comment(self):
        api = FakeAPI()
        bot.run(api, NOW)
        first_comment_count = sum(path.endswith("/comments") for _, path, _ in api.writes)
        api.writes.clear(); api.prs[1]["contexts"] = []
        bot.run(api, NOW + dt.timedelta(hours=1))
        api.writes.clear(); api.prs[1]["contexts"] = [check(completed=1)]
        bot.run(api, NOW + dt.timedelta(hours=2))
        body = api.writes[-1][2]["body"]
        self.assertIn('"repeat_failure":true', body)
        state = body.split(bot.STATE, 1)[1].split("\n-->", 1)[0]
        history = json.loads(state)
        self.assertEqual({"seen_failed", "last_required_state", "latest_failed_attempt_ids", "recovery_seen_at", "recurrent"},
                         set(history["history"]["1:" + HEAD]))
        self.assertEqual(0, sum(path.endswith("/comments") for _, path, _ in api.writes))

    def test_new_failed_attempt_is_repeat_failure(self):
        api = FakeAPI(); bot.run(api, NOW)
        api.writes.clear(); api.prs[1]["contexts"] = [check(attempt=2, completed=1)]
        bot.run(api, NOW + dt.timedelta(hours=1))
        self.assertIn('"repeat_failure":true', api.writes[-1][2]["body"])

    def test_assignee_failure_is_visible(self):
        class AssignmentFailure(FakeAPI):
            def rest(self, method, suffix, body=None):
                if suffix == "issues": raise ValueError("assignment failed")
                return super().rest(method, suffix, body)
        with self.assertRaises(ValueError): bot.run(AssignmentFailure(), NOW, summary_assignee="example-user")

    def test_missing_failed_completion_fails_without_writes(self):
        bad = check(); bad["completedAt"] = None
        api = FakeAPI(prs={1: pr(contexts=[bad])})
        with self.assertRaises(ValueError): bot.run(api, NOW)
        self.assertEqual([], api.writes)


class PaginationTests(unittest.TestCase):
    def test_rest_pagination_reads_beyond_first_hundred(self):
        api = bot.API("org/repo", "fixture"); requests = []
        def rest(method, suffix, body=None):
            requests.append((method, suffix)); return [{}] * 100 if suffix.endswith("&page=1") else [{"last": True}]
        api.rest = rest
        self.assertEqual(101, len(list(api.pages("pulls?state=open")))); self.assertIn("page=2", requests[-1][1])

    def test_graphql_paginates_required_contexts_and_threads_on_exact_head(self):
        api = bot.API("org/repo", "fixture"); requests = []
        def request(method, path, body):
            requests.append(body)
            first = body["variables"]["cursor"] is None
            data = pr(); data.update({"reviewThreads": {"nodes": [], "pageInfo": {"hasNextPage": False}}, "labels": {"nodes": []}, "reviewRequests": {"nodes": []}})
            thread_page = body["variables"]["thread_cursor"] is not None
            data["reviewThreads"] = {"nodes": [{"isResolved": False, "isOutdated": False, "comments": {"nodes": [{"createdAt": ago(25)}]}}] if thread_page else [],
                                      "pageInfo": {"hasNextPage": not thread_page, "endCursor": "thread-next"}}
            data["commits"]["nodes"][0]["commit"]["statusCheckRollup"] = {"contexts": {"nodes": [check(required=False)] if first else [check(name="required")], "pageInfo": {"hasNextPage": first, "endCursor": "next"}}}
            return {"data": {"repository": {"pullRequest": data}}}
        api.request = request
        data = api.snapshot(7)
        self.assertEqual(["required"], bot.failures(data["contexts"])[0])
        self.assertEqual("next", requests[1]["variables"]["cursor"])
        self.assertEqual("thread-next", requests[2]["variables"]["thread_cursor"])
        self.assertEqual(1, len(data["threads"]))
        self.assertIn("isRequired(pullRequestNumber:$number)", requests[0]["query"])

    def test_graphql_pagination_head_change_or_stalled_cursor_fails_closed(self):
        for mode in ("head", "cursor"):
            api = bot.API("org/repo", "fixture"); calls = []
            def request(method, path, body):
                calls.append(body)
                data = pr(head=("b" * 40 if mode == "head" and len(calls) > 1 else HEAD))
                cursor = "next" if mode == "cursor" else "next"
                data["commits"]["nodes"][0]["commit"]["statusCheckRollup"] = {"contexts": {"nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": cursor}}}
                data["reviewThreads"] = {"nodes": [], "pageInfo": {"hasNextPage": False}}
                return {"data": {"repository": {"pullRequest": data}}}
            api.request = request
            with self.assertRaises(ValueError): api.snapshot(7)

    def test_graphql_error_fails_closed(self):
        api = bot.API("org/repo", "fixture")
        api.request = lambda *args: {"errors": [{"message": "denied"}]}
        with self.assertRaises(ValueError): api.snapshot(7)


if __name__ == "__main__": unittest.main()
