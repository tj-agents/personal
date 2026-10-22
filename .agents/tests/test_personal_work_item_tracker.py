import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".agents/personal/utility/work-item"
sys.path.insert(0, str(SCRIPTS))
github = import_module("github_tracker")
records = import_module("tj_personal_work_items.records")
RequestJournal = import_module("tj_personal_work_items.request_journal").RequestJournal

CONFIG = {
    "provider": "personal:work-item",
    "repository": "owner/project",
    "issue_types": {},
}


def select_personal(root):
    agents = Path(root) / ".agents"
    agents.mkdir(exist_ok=True)
    (agents / "plugins.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "marketplaces": {"tj-agents": {"repository": "tj-agents/marketplace"}},
                "plugins": ["personal@tj-agents"],
            }
        ),
        encoding="utf-8",
    )


def item(kind="bug"):
    result = records.skeleton(kind)
    return {
        key: value if key == "kind" else "Observed " + key
        for key, value in result.items()
    }


class FakeAPI:
    def __init__(self):
        self.issues = []
        self.comments = []
        self.calls = []
        self.fail_after_create = False
        self.fail_before_create = False
        self.fail_after_comment = False
        self.projects = []
        self.placements = []
        self.fail_graphql = False

    def graphql(self, query, variables):
        if self.fail_graphql:
            raise github.APIError("missing project scope", 403)
        if query.startswith("query($owner:String!){repositoryOwner"):
            return {
                "repositoryOwner": {
                    "id": "owner-id",
                    "projectsV2": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": copy.deepcopy(self.projects),
                    },
                }
            }
        if query.startswith("query($owner:String!,$name:String!){repository("):
            return {"repository": {"id": "repository-id"}}
        if "createProjectV2(" in query:
            status = {
                "id": "status",
                "name": "Status",
                "options": [
                    {"id": "todo", "name": "Todo"},
                    {"id": "done", "name": "Done"},
                ],
            }
            project = {
                "id": "board-" + variables["title"],
                "title": variables["title"],
                "closed": False,
                "fields": {"nodes": [status, {}]},
            }
            self.projects.append(project)
            return {"createProjectV2": {"projectV2": copy.deepcopy(project)}}
        if "createProjectV2Field" in query:
            project = next(
                project
                for project in self.projects
                if project["id"] == variables["project"]
            )
            options = [{"id": "kind-" + name, "name": name} for name in records.KINDS]
            field = {"id": "kind", "name": "Kind", "options": options}
            project["fields"]["nodes"].append(field)
            return {"createProjectV2Field": {"projectV2Field": copy.deepcopy(field)}}
        if "addProjectV2ItemById" in query:
            return {
                "addProjectV2ItemById": {
                    "item": {"id": variables["project"] + ":" + variables["content"]}
                }
            }
        if "updateProjectV2ItemFieldValue" in query:
            self.placements.append(
                (variables["project"], variables["field"], variables["option"])
            )
            return {
                "updateProjectV2ItemFieldValue": {
                    "projectV2Item": {"id": variables["item"]}
                }
            }
        raise AssertionError(query)

    def request(self, method, endpoint, payload=None, paginate=False):
        self.calls.append((method, endpoint, copy.deepcopy(payload)))
        if endpoint == "graphql":
            return {"data": self.graphql(payload["query"], payload["variables"])}
        base = "repos/owner/project/issues"
        if method == "GET" and endpoint == base + "?state=all&per_page=100":
            return copy.deepcopy(self.issues)
        if method == "GET" and endpoint == "repos/owner/project/issue-types":
            return [{"name": name} for name in ("Task", "Feature", "Story", "Bug")]
        if endpoint == "repos/owner/project/issues/comments/1":
            return copy.deepcopy(self.comments[0])
        if endpoint.startswith(base + "/1/comments"):
            if method == "GET":
                return copy.deepcopy(self.comments)
            value = {
                "id": len(self.comments) + 1,
                "body": payload["body"],
                "html_url": "https://github.com/owner/project/issues/1#issuecomment-1",
            }
            self.comments.append(value)
            if self.fail_after_comment:
                raise github.APIError("lost response")
            return copy.deepcopy(value)
        if method == "POST" and endpoint == base:
            if self.fail_before_create:
                raise github.APIError("rejected", 403)
            number = len(self.issues) + 1
            value = {
                "number": number,
                "state": "open",
                "html_url": f"https://github.com/owner/project/issues/{number}",
                "node_id": f"issue-{number}",
                **payload,
            }
            self.issues.append(value)
            if self.fail_after_create:
                raise github.APIError("lost response")
            return copy.deepcopy(value)
        if endpoint == base + "/1":
            if method == "PATCH":
                self.issues[0].update(payload)
            return copy.deepcopy(self.issues[0])
        raise AssertionError((method, endpoint, payload))


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.tracker = github.Tracker(CONFIG, self.api)

    def test_create_retries_reconcile_the_original_issue(self):
        first = self.tracker.create(item(), "request-0001")
        second = self.tracker.create(item(), "request-0001")
        self.assertEqual(first["identity"], second["identity"])
        self.assertTrue(second["reconciled"])
        self.assertEqual(1, len(self.api.issues))
        self.assertEqual(
            1,
            sum(
                method == "POST" and endpoint != "graphql"
                for method, endpoint, _ in self.api.calls
            ),
        )

    def test_lost_create_response_is_reconciled_without_reposting(self):
        self.api.fail_after_create = True
        self.assertTrue(self.tracker.create(item(), "request-0001")["reconciled"])
        self.assertEqual(1, len(self.api.issues))

    def test_rejected_create_does_not_retry_post(self):
        self.api.fail_before_create = True
        with self.assertRaisesRegex(records.ItemError, "uncertain or rejected"):
            self.tracker.create(item(), "request-0001")
        self.assertEqual(1, sum(method == "POST" for method, _, _ in self.api.calls))

    def test_collision_and_duplicates_remain_visible(self):
        self.tracker.create(item(), "request-0001")
        with self.assertRaisesRegex(records.ItemError, "different creation facts"):
            self.tracker.create({**item(), "title": "Different"}, "request-0001")
        self.api.issues.append(copy.deepcopy(self.api.issues[0]))
        with self.assertRaisesRegex(records.ItemError, "multiple issues"):
            self.tracker.create(item(), "request-0001")

    def test_native_type_is_set_only_when_the_repository_offers_it(self):
        tracker = github.Tracker(
            {**CONFIG, "issue_types": {"feature": "Feature"}}, self.api
        )
        tracker.create(item("feature"), "request-0001")
        self.assertEqual("Feature", self.api.issues[0]["type"])
        tracker = github.Tracker(
            {**CONFIG, "issue_types": {"bug": "Missing"}}, self.api
        )
        tracker.create(item(), "request-0002")
        self.assertNotIn("type", self.api.issues[1])

    def test_created_item_lands_on_repository_and_owner_boards(self):
        created = self.tracker.create(item("debt"), "request-0001")
        self.assertEqual({"placed": ["project", "owner"]}, created["boards"])
        self.assertEqual(
            ["project", "owner"], [project["title"] for project in self.api.projects]
        )
        for board in ("board-project", "board-owner"):
            self.assertIn((board, "status", "todo"), self.api.placements)
            self.assertIn((board, "kind", "kind-debt"), self.api.placements)
        self.tracker.create(item("debt"), "request-0001")
        self.assertEqual(2, len(self.api.projects))
        self.assertEqual(
            2, sum(field == "status" for _, field, _ in self.api.placements)
        )

    def test_issue_urls_match_the_origin_case_insensitively(self):
        self.tracker.create(item(), "request-0001")
        tracker = github.Tracker({**CONFIG, "repository": "Owner/Project"}, self.api)
        self.assertEqual(
            "Owner/Project#1", tracker.compact(self.api.issues[0])["identity"]
        )
        self.assertEqual(
            1,
            github.issue_number(
                "https://github.com/owner/project/issues/1", "Owner/Project"
            ),
        )

    def test_board_failure_reports_without_losing_the_created_issue(self):
        self.api.fail_graphql = True
        created = self.tracker.create(item(), "request-0001")
        self.assertFalse(created["reconciled"])
        self.assertEqual([], created["boards"]["placed"])
        self.assertIn("board placement incomplete", created["boards"]["error"])
        self.assertEqual(1, len(self.api.issues))

    def test_story_uses_native_type_and_round_trips_its_managed_kind(self):
        tracker = github.Tracker(
            {**CONFIG, "issue_types": {"story": "Story"}}, self.api
        )
        created = tracker.create(item("story"), "request-0001")
        self.assertEqual("Story", self.api.issues[0]["type"])
        self.assertEqual("story", created["kind"])
        self.assertEqual("story", tracker.compact(self.api.issues[0])["kind"])

    def test_update_refuses_stale_hash_and_manual_body_edits(self):
        created = self.tracker.create(item(), "request-0001")
        updated = {**item(), "evidence": "New evidence"}
        with self.assertRaisesRegex(records.ItemError, "changed"):
            self.tracker.update(1, updated, "stale")
        self.tracker.update(1, updated, created["body_hash"])
        self.assertIn("New evidence", self.api.issues[0]["body"])
        self.api.issues[0]["body"] = "Manual text\n" + self.api.issues[0]["body"]
        with self.assertRaisesRegex(records.ItemError, "changed"):
            self.tracker.update(1, updated, github.digest(self.api.issues[0]["body"]))

    def test_update_preserves_creation_identity_and_rejects_kind_changes(self):
        created = self.tracker.create(item(), "request-0001")
        updated = {**item(), "title": "Updated"}
        self.tracker.update(1, updated, created["body_hash"])
        self.assertTrue(self.tracker.create(item(), "request-0001")["reconciled"])
        current = self.tracker.compact(self.api.issues[0])
        with self.assertRaisesRegex(records.ItemError, "cannot change"):
            self.tracker.update(1, item("task"), current["body_hash"])

    def test_uncertain_comment_reconciles_and_changed_comment_refuses_retry(self):
        self.tracker.create(item(), "request-0001")
        self.api.fail_after_comment = True
        first = self.tracker.comment(1, "Actual verification", "comment-0001", "close")
        second = self.tracker.comment(1, "Actual verification", "comment-0001", "close")
        self.assertEqual(first, second)
        self.assertEqual(1, len(self.api.comments))
        self.api.comments[0]["body"] = "Changed\n" + self.api.comments[0]["body"]
        with self.assertRaisesRegex(records.ItemError, "different facts"):
            self.tracker.comment(1, "Actual verification", "comment-0001", "close")

    def test_pull_requests_and_oversized_bodies_cannot_be_mutated(self):
        self.tracker.create(item(), "request-0001")
        self.api.issues[0]["pull_request"] = {}
        self.assertEqual([], self.tracker.all())
        with self.assertRaisesRegex(records.ItemError, "expected issue"):
            self.tracker.get(1)
        with self.assertRaisesRegex(records.ItemError, "exceeds"):
            self.tracker.create({**item(), "evidence": "a" * 65536}, "request-0002")
        with self.assertRaises(records.ItemError):
            self.tracker.comment(1, " ", "comment-0001")

    def test_close_records_verification_before_closing_and_is_repeatable(self):
        self.tracker.create(item(), "request-0001")
        with tempfile.TemporaryDirectory() as directory:
            text = Path(directory) / "verification.txt"
            text.write_text("Observed tests passed", encoding="utf-8")
            args = argparse.Namespace(
                command="close",
                root=directory,
                item="owner/project#1",
                request_id="close-0001",
                text_file=str(text),
            )
            with (
                patch.object(github, "GitHub", return_value=self.api),
                patch.object(github, "selection", return_value=CONFIG),
                patch.object(github, "RequestJournal", return_value=None),
            ):
                result = github.execute(args)
                self.assertEqual("closed", result["state"])
                self.assertIn("Observed tests passed", self.api.comments[0]["body"])
                repeated = github.execute(args)
                self.assertTrue(repeated["already_closed"])
                self.assertEqual(1, len(self.api.comments))
            writes = [
                (method, endpoint)
                for method, endpoint, _ in self.api.calls
                if method in ("POST", "PATCH")
            ]
            self.assertTrue(writes[-2][1].endswith("/comments"))
            self.assertEqual("PATCH", writes[-1][0])

    def test_issue_identity_never_crosses_selected_repository(self):
        for value in ("owner/project#1", "https://github.com/owner/project/issues/1"):
            self.assertEqual(1, github.issue_number(value, "owner/project"))
        invalid = (
            "1",
            "other/project#1",
            "owner/project#0",
            "https://github.com/owner/project/pull/1",
        )
        for value in (*invalid, "owner/project#" + chr(0x661)):
            with self.assertRaises(records.ItemError):
                github.issue_number(value, "owner/project")


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="work-item receipts ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.api = FakeAPI()
        self.journal = RequestJournal(self.root)
        self.tracker = github.Tracker(CONFIG, self.api, self.journal)

    def stale_lists(self):
        original = self.api.request

        def request(method, endpoint, payload=None, paginate=False):
            if (
                method == "GET"
                and endpoint == "repos/owner/project/issues?state=all&per_page=100"
            ):
                return []
            if method == "GET" and endpoint.endswith("/comments?per_page=100"):
                return []
            return original(method, endpoint, payload, paginate)

        self.api.request = request

    def test_repeat_uses_returned_identity_even_when_list_omits_new_issue(self):
        created = self.tracker.create(item(), "request-0001")
        self.stale_lists()
        reopened = github.Tracker(CONFIG, self.api, RequestJournal(self.root))
        repeated = reopened.create(item(), "request-0001")
        self.assertEqual(created["identity"], repeated["identity"])
        self.assertTrue(repeated["reconciled"])
        self.assertEqual(1, len(self.api.issues))
        with self.assertRaisesRegex(records.ItemError, "differs"):
            reopened.create({**item(), "title": "Different"}, "request-0001")

    def test_uncertain_post_and_stale_list_never_repost_on_retry(self):
        self.stale_lists()
        self.api.fail_after_create = True
        for _ in range(2):
            with self.assertRaisesRegex(records.ItemError, "uncertain"):
                self.tracker.create(item(), "request-0001")
        self.assertEqual(1, len(self.api.issues))
        with self.assertRaisesRegex(records.ItemError, "uncertain"):
            self.tracker.create(item(), "cross-machine-request", reconcile_only=True)
        self.assertEqual(1, len(self.api.issues))

    def test_comment_receipts_reconcile_by_identity_when_list_is_stale(self):
        self.tracker.create(item(), "request-0001")
        first = self.tracker.comment(1, "Verified", "comment-0001")
        self.stale_lists()
        self.assertEqual(first, self.tracker.comment(1, "Verified", "comment-0001"))
        self.assertEqual(1, len(self.api.comments))
        with self.assertRaisesRegex(records.ItemError, "uncertain"):
            self.tracker.comment(
                1, "Uncertain on another computer", "comment-0002", reconcile_only=True
            )
        self.assertEqual(1, len(self.api.comments))
        self.api.comments[0]["body"] = "Manual edit"
        with self.assertRaisesRegex(records.ItemError, "changed"):
            self.tracker.comment(1, "Verified", "comment-0001")

    def test_reserved_and_corrupt_receipts_fail_closed(self):
        self.journal.reserve("request", "fingerprint")
        with self.assertRaisesRegex(records.ItemError, "already reserved"):
            self.journal.reserve("request", "fingerprint")
        self.journal.path("request").write_text("invalid", encoding="utf-8")
        with self.assertRaisesRegex(records.ItemError, "unreadable"):
            self.journal.read("request", "fingerprint")


class SelectionTests(unittest.TestCase):
    def test_malformed_personal_adoption_selections_are_refused(self):
        base = {
            "schema_version": 1,
            "plugins": ["personal@tj-agents"],
            "marketplaces": {"tj-agents": {"repository": "tj-agents/marketplace"}},
        }
        malformed = (
            {**base, "plugins": "personal@tj-agents"},
            {**base, "plugins": ["personal@tj-agents", 1]},
            {**base, "marketplaces": "tj-agents"},
            {**base, "marketplaces": {"tj-agents": "marketplace"}},
            {
                **base,
                "marketplaces": {
                    "tj-agents": {"repository": ["tj-agents/marketplace"]}
                },
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / ".agents"
            agents.mkdir()
            path = agents / "plugins.json"
            for selection in malformed:
                with self.subTest(selection=selection):
                    path.write_text(json.dumps(selection), encoding="utf-8")
                    with self.assertRaisesRegex(records.ItemError, "explicit personal"):
                        github.personal_adoption(root)

    def test_personal_selection_alone_selects_the_origin_tracker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            with self.assertRaisesRegex(records.ItemError, "explicit personal"):
                github.selection(root)
            select_personal(root)
            with patch.object(
                github, "source_repository", return_value="owner/project"
            ):
                config = github.selection(root)
            self.assertEqual("owner/project", config["repository"])
            self.assertEqual("personal:work-item", config["provider"])
            self.assertEqual(github.ISSUE_TYPES, config["issue_types"])
            (root / ".problem-records.json").write_text(
                json.dumps({"schema_version": 1, "provider": "infonetica:work-item"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                records.ItemError, "another problem-record provider"
            ):
                github.selection(root)

    def test_gh_transport_uses_argument_arrays_and_flattens_all_pages(self):
        response = subprocess.CompletedProcess(
            [], 0, stdout='[[{"number":1}],[{"number":2}]]', stderr=""
        )
        with (
            patch.object(github.shutil, "which", return_value="gh.exe"),
            patch.object(github.subprocess, "run", return_value=response) as run,
        ):
            result = github.GitHub().request(
                "GET", "repos/owner/project/issues", paginate=True
            )
            self.assertEqual([1, 2], [v["number"] for v in result])
            args, kwargs = run.call_args
            self.assertIn("--slurp", args[0])
            self.assertNotIn("shell", kwargs)
            self.assertEqual("utf-8", kwargs["encoding"])

    @unittest.skipUnless(os.name == "nt", "Windows executable selection")
    def test_gh_transport_uses_the_front_path_bot_identity_shim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shim = root / "bot-identity"
            real = root / "real-gh"
            shim.mkdir()
            real.mkdir()
            recorder = shim / "dummy.py"
            recorder.write_text(
                "import json\n"
                "import os\n"
                "from pathlib import Path\n"
                "import sys\n"
                "record = {'argv': sys.argv[1:],\n"
                "          'agent': os.environ.get('TJ_AGENT')}\n"
                "output = Path(__file__).with_name('arguments.json')\n"
                "output.write_text(json.dumps(record))\n"
                "print('[[{\\\"number\\\":1}]]')\n",
                encoding="utf-8",
            )
            (shim / "gh.cmd").write_text(
                f'@"{sys.executable}" -B "{recorder}" gh %*\r\n',
                encoding="utf-8",
            )
            (real / "gh.exe").touch()
            path = os.pathsep.join((str(shim), str(real)))
            previous = {
                name: github.os.environ.get(name)
                for name in ("PATH", "PATHEXT", "TJ_AGENT")
            }
            try:
                github.os.environ.update(
                    {"PATH": path, "PATHEXT": ".EXE;.CMD", "TJ_AGENT": "1"}
                )
                result = github.GitHub().request(
                    "GET",
                    "repos/owner/project/issues?state=all&per_page=100",
                    paginate=True,
                )
            finally:
                for name, value in previous.items():
                    if value is None:
                        github.os.environ.pop(name, None)
                    else:
                        github.os.environ[name] = value
            recorded = json.loads((shim / "arguments.json").read_text(encoding="utf-8"))
            self.assertEqual([{"number": 1}], result)
            self.assertEqual("1", recorded["agent"])
            self.assertEqual("repos/owner/project/issues", recorded["argv"][-1])
            self.assertNotIn("?", recorded["argv"][-1])
            self.assertEqual(
                ["state=all", "per_page=100"],
                [
                    recorded["argv"][index + 1]
                    for index, value in enumerate(recorded["argv"])
                    if value == "--raw-field"
                ],
            )
            self.assertIn("--paginate", recorded["argv"])
            self.assertIn("--slurp", recorded["argv"])


if __name__ == "__main__":
    unittest.main()
