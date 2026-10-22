import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import parse_qsl, urlparse

from runtime_bootstrap import bootstrap

bootstrap()

from tj_personal_work_items.records import ItemError, KINDS, read_input, render
from tj_personal_work_items.request_journal import RequestJournal


REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}")
MARKER = re.compile(r"\n<!-- work-item:v1 (.+) -->\n?\Z")
COMMENT = re.compile(r"\n<!-- work-item-comment:v1 (.+) -->\n?\Z")
ISSUE_TYPES = {"feature": "Feature", "story": "Story", "task": "Task", "bug": "Bug", "mistake": "Task", "debt": "Task"}
BOARD_STATUS = "Todo"


class APIError(ItemError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class GitHub:
    def __init__(self, timeout=60):
        self.timeout = timeout

    def request(self, method, endpoint, payload=None, paginate=False):
        executable = shutil.which("gh")
        if executable is None:
            raise APIError("GitHub CLI is unavailable; verify gh authentication and access")
        path, separator, query = endpoint.partition("?")
        command = [executable, "api", "--hostname", "github.com", "--method", method,
                   "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: 2026-03-10"]
        for key, value in parse_qsl(query, keep_blank_values=True) if separator else ():
            command.extend(("--raw-field", f"{key}={value}"))
        if payload is not None:
            command.extend(["--input", "-"])
        if paginate:
            command.extend(["--paginate", "--slurp"])
        command.append(path)
        env = {**os.environ, "GH_PROMPT_DISABLED": "1"}
        env.pop("GH_DEBUG", None)
        try:
            result = subprocess.run(command, input=json_text(payload) if payload is not None else None,
                                    capture_output=True, text=True, encoding="utf-8", timeout=self.timeout,
                                    env=env, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise APIError("GitHub transport unavailable; a write outcome may be uncertain") from error
        if result.returncode:
            status = re.search(r"HTTP (\d{3})", result.stderr)
            code = int(status.group(1)) if status else None
            raise APIError(f"GitHub {method} failed (HTTP {code or 'unknown'}); verify gh authentication and access", code)
        try:
            data = json.loads(result.stdout)
            if paginate:
                if not isinstance(data, list) or any(not isinstance(page, list) for page in data):
                    raise ValueError("invalid paginated response")
                return [item for page in data for item in page]
            return data
        except (ValueError, TypeError) as error:
            raise APIError("GitHub returned an invalid response; a write outcome may be uncertain") from error


def source_primary(root):
    root = Path(root).resolve()
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)
        inventory = subprocess.run(["git", "-C", str(root), "worktree", "list", "--porcelain", "-z"],
                                   capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)
        if top.returncode or inventory.returncode or not top.stdout.rstrip("\r\n") or not inventory.stdout.endswith("\0\0"):
            raise ItemError("cannot resolve source primary checkout from Git worktrees")
        current = Path(top.stdout.rstrip("\r\n")).resolve()
        checkouts = []
        for block in inventory.stdout[:-2].split("\0\0"):
            fields = block.split("\0")
            if not fields[0].startswith("worktree ") or sum(field.startswith("worktree ") for field in fields) != 1:
                raise ItemError("invalid Git worktree inventory")
            location = fields[0][len("worktree "):]
            if not location or not Path(location).is_absolute():
                raise ItemError("invalid Git worktree checkout path")
            checkouts.append(Path(location).resolve())
        if current not in checkouts or not checkouts[0].is_dir():
            raise ItemError("source primary checkout is unavailable or current checkout is absent from Git worktrees")
        return checkouts[0]
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise ItemError("cannot resolve source primary checkout from Git worktrees") from error


def source_repository(root):
    result = subprocess.run(["git", "-C", str(root), "config", "--get", "remote.origin.url"],
                            capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)
    remote = result.stdout.strip()
    if remote.startswith("git@github.com:"):
        repo = remote[len("git@github.com:"):]
    else:
        parsed = urlparse(remote)
        if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
            raise ItemError("origin must identify a source repository on github.com")
        repo = parsed.path.lstrip("/")
    repo = repo.removesuffix(".git")
    if result.returncode or not REPOSITORY.fullmatch(repo):
        raise ItemError("origin must identify owner/repository on github.com")
    return repo


def personal_adoption(root):
    path = root / ".agents" / "plugins.json"
    if path.is_symlink():
        raise ItemError("personal adoption selection must be a regular repository file")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ItemError("explicit personal adoption is required") from error
    plugins = value.get("plugins") if isinstance(value, dict) else None
    marketplaces = value.get("marketplaces") if isinstance(value, dict) else None
    marketplace = marketplaces.get("tj-agents") if isinstance(marketplaces, dict) else None
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or not isinstance(plugins, list)
        or any(not isinstance(plugin, str) for plugin in plugins)
        or not isinstance(marketplaces, dict)
        or any(
            not isinstance(name, str) or not isinstance(details, dict)
            for name, details in marketplaces.items()
        )
        or not isinstance(marketplace, dict)
        or not isinstance(marketplace.get("repository"), str)
        or value["schema_version"] != 1
        or "personal@tj-agents" not in plugins
        or marketplace["repository"] != "tj-agents/marketplace"
    ):
        raise ItemError("explicit personal adoption is required")
    return {"root": str(root), "provider": "personal:work-item"}


def selection(root):
    root = source_primary(root)
    personal_adoption(root)
    declared = root / ".problem-records.json"
    if declared.is_symlink():
        raise ItemError("problem-record declaration must be a regular repository file")
    if declared.exists():
        try:
            value = json.loads(declared.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            raise ItemError("the repository's problem-record declaration is unreadable") from error
        if value != {"schema_version": 1, "provider": "personal:work-item"}:
            raise ItemError("the repository declares another problem-record provider")
    return {"provider": "personal:work-item", "repository": source_repository(root), "issue_types": dict(ISSUE_TYPES)}


def request_id(value):
    if not REQUEST.fullmatch(value):
        raise ItemError("request-id must contain 8–128 letters, digits, underscores or hyphens")
    return value


def issue_number(value, repository):
    prefix = f"https://github.com/{repository}/issues/".lower()
    identity = (repository + "#").lower()
    folded = value.lower() if value.isascii() else ""
    number = folded[len(prefix):] if folded.startswith(prefix) else folded[len(identity):] if folded.startswith(identity) else ""
    if not number.isascii() or not number.isdecimal() or int(number) <= 0:
        raise ItemError("item must be a full issue URL or repository#number matching the selected repository")
    return int(number)


def metadata(body):
    if not isinstance(body, str):
        raise ItemError("managed issue body must be text")
    match = MARKER.search(body)
    if not match:
        raise ItemError("issue is not a managed personal work item")
    try:
        value = json.loads(match.group(1))
        if not isinstance(value, dict) or set(value) not in ({"request_id", "kind", "creation_hash", "render_hash"}, {"request_id", "kind", "creation_hash", "render_hash", "kind_hash"}):
            raise ValueError("metadata shape")
        if value["kind"] not in KINDS or not isinstance(value["request_id"], str):
            raise ValueError("metadata kind/request")
        request_id(value["request_id"])
        if any(not isinstance(value[k], str) or not re.fullmatch(r"[a-f0-9]{64}", value[k]) for k in ("creation_hash", "render_hash", *(["kind_hash"] if "kind_hash" in value else []))):
            raise ValueError("metadata digest")
        return value, body[:match.start()]
    except (ValueError, TypeError) as error:
        raise ItemError("invalid managed issue metadata") from error


def body_for(item, request, existing=None):
    text = render(item).rstrip("\n")
    info = {"request_id": request, "kind": item["kind"],
            "creation_hash": existing["creation_hash"] if existing else digest(json_text(item)), "render_hash": digest(text),
            "kind_hash": digest(item["kind"] + "\n" + text)}
    body = text + "\n<!-- work-item:v1 " + json_text(info) + " -->\n"
    if len(body) > 65536:
        raise ItemError("rendered issue body exceeds 65536 characters")
    return body


FIELDS = "fields(first:50){nodes{... on ProjectV2SingleSelectField{id name options{id name}}}}"
BOARDS = "query($owner:String!){repositoryOwner(login:$owner){... on ProjectV2Owner{id projectsV2(first:100,query:\"is:open\"){pageInfo{hasNextPage} nodes{id title closed " + FIELDS + "}}}}}"
REPOSITORY_ID = "query($owner:String!,$name:String!){repository(owner:$owner,name:$name){id}}"
CREATE_BOARD = "mutation($owner:ID!,$title:String!,$repository:ID!){createProjectV2(input:{ownerId:$owner,title:$title,repositoryId:$repository}){projectV2{id title " + FIELDS + "}}}"
KIND_COLORS = {"bug": "RED", "mistake": "ORANGE", "debt": "YELLOW", "feature": "GREEN", "task": "BLUE", "story": "PURPLE"}
KIND_FIELD = ("mutation($project:ID!){createProjectV2Field(input:{projectId:$project,dataType:SINGLE_SELECT,name:\"Kind\",singleSelectOptions:["
              + ",".join('{name:"%s",color:%s,description:""}' % (kind, KIND_COLORS.get(kind, "GRAY")) for kind in KINDS)
              + "]}){projectV2Field{... on ProjectV2SingleSelectField{id name options{id name}}}}}")
ADD_ITEM = "mutation($project:ID!,$content:ID!){addProjectV2ItemById(input:{projectId:$project,contentId:$content}){item{id status:fieldValueByName(name:\"Status\"){... on ProjectV2ItemFieldSingleSelectValue{name}}}}}"
SET_OPTION = "mutation($project:ID!,$item:ID!,$field:ID!,$option:String!){updateProjectV2ItemFieldValue(input:{projectId:$project,itemId:$item,fieldId:$field,value:{singleSelectOptionId:$option}}){projectV2Item{id}}}"


class Tracker:
    def __init__(self, config, api=None, journal=None):
        self.config = config
        self.repo = config["repository"]
        self.api = api or GitHub()
        self.journal = journal
        self.endpoint = "repos/" + self.repo + "/issues"

    def all(self):
        return [issue for issue in self.api.request("GET", self.endpoint + "?state=all&per_page=100", paginate=True)
                if "pull_request" not in issue]

    def get(self, number):
        issue = self.api.request("GET", self.endpoint + f"/{number}")
        if not isinstance(issue, dict) or issue.get("number") != number or "pull_request" in issue:
            raise ItemError("target is not the expected issue")
        metadata(issue.get("body"))
        return issue

    def compact(self, issue):
        if not isinstance(issue, dict) or type(issue.get("number")) is not int or issue["number"] <= 0:
            raise ItemError("invalid issue response identity")
        if str(issue.get("html_url")).casefold() != f"https://github.com/{self.repo}/issues/{issue['number']}".casefold() or issue.get("state") not in ("open", "closed") or not isinstance(issue.get("title"), str):
            raise ItemError("invalid issue response fields")
        info, _ = metadata(issue.get("body"))
        return {"identity": f"{self.repo}#{issue['number']}", "url": issue["html_url"], "state": issue["state"],
                "title": issue["title"], "kind": info["kind"], "body_hash": digest(issue["body"])}

    def find_request(self, request, item):
        found = []
        for issue in self.all():
            try:
                info, _ = metadata(issue.get("body"))
            except ItemError:
                continue
            if info["request_id"] == request:
                if info["creation_hash"] != digest(json_text(item)):
                    raise ItemError("request-id already exists with different creation facts")
                found.append(issue)
        if len(found) > 1:
            raise ItemError("request-id has multiple issues; reconcile their ownership before continuing")
        return found[0] if found else None

    def create(self, item, request, reconcile_only=False):
        request_id(request)
        body = body_for(item, request)
        key = self.repo + ":create:" + request
        fingerprint = digest(json_text(item))
        receipt = self.journal.read(key, fingerprint) if self.journal else None
        existing = self.find_request(request, item)
        if existing is None and receipt and receipt["resource_id"]:
            existing = self.get(receipt["resource_id"])
            info, _ = metadata(existing["body"])
            if info["request_id"] != request or info["creation_hash"] != fingerprint:
                raise ItemError("returned issue no longer matches its request receipt")
        if existing:
            if self.journal:
                self.journal.complete(key, fingerprint, existing["number"])
            return {**self.compact(existing), "reconciled": True, "boards": self.place(existing, item["kind"])}
        if receipt or reconcile_only:
            raise ItemError("request outcome remains uncertain; reconcile without another POST")
        payload = {"title": item["title"], "body": body}
        issue_type = self.config["issue_types"].get(item["kind"])
        if issue_type:
            try:
                available = self.api.request("GET", "repos/" + self.repo + "/issue-types")
            except APIError as error:
                if error.status != 404:
                    raise
                available = []
            names = [entry.get("name") for entry in available if isinstance(entry, dict)] if isinstance(available, list) else []
            if issue_type in names:
                payload["type"] = issue_type
        if self.journal:
            self.journal.reserve(key, fingerprint)
        try:
            issue = self.api.request("POST", self.endpoint, payload)
            result = self.compact(issue)
            if self.journal:
                self.journal.complete(key, fingerprint, issue["number"])
        except (APIError, ItemError, KeyError, TypeError):
            existing = self.find_request(request, item)
            if existing:
                if self.journal:
                    self.journal.complete(key, fingerprint, existing["number"])
                return {**self.compact(existing), "reconciled": True, "boards": self.place(existing, item["kind"])}
            raise ItemError("create outcome uncertain or rejected; retain request-id and reconcile before retrying")
        return {**result, "reconciled": False, "boards": self.place(issue, item["kind"])}

    def graphql(self, query, **variables):
        response = self.api.request("POST", "graphql", {"query": query, "variables": variables})
        if not isinstance(response, dict) or response.get("errors") or not isinstance(response.get("data"), dict):
            raise APIError("GitHub GraphQL request failed; verify gh has the project scope")
        return response["data"]

    def boards(self, owner):
        data = self.graphql(BOARDS, owner=owner)["repositoryOwner"]
        if data["projectsV2"]["pageInfo"]["hasNextPage"]:
            raise APIError("the owner has more than 100 open projects; place the item manually")
        found = {}
        for node in data["projectsV2"]["nodes"]:
            if not node["closed"]:
                found.setdefault(node["title"], node)
        return data["id"], found

    def board(self, owner_id, found, title, owner):
        project = found.get(title)
        if project is None:
            repository = self.graphql(REPOSITORY_ID, owner=owner, name=self.repo.split("/")[1])["repository"]["id"]
            project = self.graphql(CREATE_BOARD, owner=owner_id, title=title, repository=repository)["createProjectV2"]["projectV2"]
        fields = {field["name"]: field for field in project["fields"]["nodes"] if field}
        if "Kind" not in fields:
            created = self.graphql(KIND_FIELD, project=project["id"])["createProjectV2Field"]["projectV2Field"]
            fields["Kind"] = created
        return project["id"], fields

    def place(self, issue, kind):
        owner, name = self.repo.split("/")
        placed = []
        try:
            owner_id, found = self.boards(owner)
            for title in dict.fromkeys((name, owner)):
                project, fields = self.board(owner_id, found, title, owner)
                entry = self.graphql(ADD_ITEM, project=project, content=issue["node_id"])["addProjectV2ItemById"]["item"]
                values = (("Kind", kind),) if entry["status"] else (("Status", BOARD_STATUS), ("Kind", kind))
                for field, value in values:
                    option = next((o["id"] for o in fields.get(field, {}).get("options", []) if o["name"] == value), None)
                    if option:
                        self.graphql(SET_OPTION, project=project, item=entry["id"], field=fields[field]["id"], option=option)
                placed.append(title)
        except (APIError, KeyError, TypeError) as error:
            return {"placed": placed, "error": "board placement incomplete: " + str(error)}
        return {"placed": placed}

    def update(self, number, item, expected_hash):
        issue = self.get(number)
        info, old_text = metadata(issue["body"])
        if digest(issue["body"]) != expected_hash or digest(old_text) != info["render_hash"]:
            raise ItemError("issue changed; read and reconcile current content before updating")
        if item["kind"] != info["kind"]:
            raise ItemError("update cannot change the work-item kind")
        payload = {"title": item["title"], "body": body_for(item, info["request_id"], info)}
        try:
            return self.compact(self.api.request("PATCH", self.endpoint + f"/{number}", payload))
        except APIError as error:
            raise ItemError("update outcome uncertain; read the issue before another update") from error

    def comment(self, number, text, request, operation="note", reconcile_only=False):
        request_id(request)
        if not isinstance(text, str) or not text.strip():
            raise ItemError("comment/verification text must be nonempty")
        info = {"request_id": request, "operation": operation, "content_hash": digest(text)}
        body = text + "\n<!-- work-item-comment:v1 " + json_text(info) + " -->\n"
        if len(body) > 65536:
            raise ItemError("comment exceeds 65536 characters")
        endpoint = self.endpoint + f"/{number}/comments"
        key = self.repo + f":comment:{number}:" + request
        fingerprint = digest(json_text(info))
        receipt = self.journal.read(key, fingerprint) if self.journal else None
        def reconcile():
            found = []
            for comment in self.api.request("GET", endpoint + "?per_page=100", paginate=True):
                match = COMMENT.search(comment.get("body") or "")
                if not match:
                    continue
                try:
                    previous = json.loads(match.group(1))
                except ValueError:
                    continue
                if isinstance(previous, dict) and previous.get("request_id") == request:
                    if previous != info or digest(comment["body"][:match.start()]) != info["content_hash"]:
                        raise ItemError("comment request-id exists with different facts")
                    found.append(comment)
            if len(found) > 1:
                raise ItemError("comment request-id has duplicates; reconcile before continuing")
            if not found and receipt and receipt["resource_id"]:
                comment = self.api.request("GET", "repos/" + self.repo + "/issues/comments/" + str(receipt["resource_id"]))
                if comment.get("body") != body:
                    raise ItemError("comment changed since its request receipt")
                found.append(comment)
            return found[0] if found else None
        existing = reconcile()
        if existing:
            if self.journal:
                self.journal.complete(key, fingerprint, existing["id"])
            return existing
        if receipt or reconcile_only:
            raise ItemError("comment outcome remains uncertain; reconcile without another POST")
        if self.journal:
            self.journal.reserve(key, fingerprint)
        try:
            comment = self.api.request("POST", endpoint, {"body": body})
            if self.journal:
                self.journal.complete(key, fingerprint, comment["id"])
            return comment
        except APIError:
            existing = reconcile()
            if existing:
                if self.journal:
                    self.journal.complete(key, fingerprint, existing["id"])
                return existing
            raise ItemError("comment outcome uncertain or rejected; retain request-id and reconcile before retrying")


def add_commands(commands, names=None):
    names = names or ("create", "read", "list", "state", "update", "note", "link", "close")
    for name in names:
        command = commands.add_parser(name)
        command.add_argument("--root", default=".")
        if name in ("create", "update"):
            command.add_argument("--input", required=True)
        if name not in ("create", "list"):
            command.add_argument("--item", required=True)
        if name in ("create", "note", "link", "close"):
            command.add_argument("--request-id", required=True)
        if name in ("create", "note", "link", "close"):
            command.add_argument("--reconcile-only", action="store_true")
        if name == "update":
            command.add_argument("--expected-hash", required=True)
        if name == "list":
            command.add_argument("--kind", choices=KINDS)
            command.add_argument("--state", choices=("open", "closed", "all"), default="open")
        if name == "read":
            command.add_argument("--body", action="store_true")
            command.add_argument("--comments", action="store_true")
        if name in ("note", "close"):
            command.add_argument("--text-file", required=True)
        if name == "link":
            command.add_argument("--target", required=True)


def execute(args):
    api = GitHub()
    tracker = Tracker(selection(args.root), api, RequestJournal(args.root))
    if args.command == "create":
        return tracker.create(read_input(args.input), args.request_id, args.reconcile_only)
    if args.command == "list":
        result = []
        for issue in tracker.all():
            try:
                item = tracker.compact(issue)
            except ItemError:
                continue
            if (not args.kind or item["kind"] == args.kind) and (args.state == "all" or item["state"] == args.state):
                result.append(item)
        return {"repository": tracker.repo, "items": result}
    number = issue_number(args.item, tracker.repo)
    issue = tracker.get(number)
    if args.command == "read":
        result = tracker.compact(issue)
        if args.body:
            result["body"] = issue["body"]
        if args.comments:
            result["comments"] = api.request("GET", tracker.endpoint + f"/{number}/comments?per_page=100", paginate=True)
        return result
    if args.command == "state":
        return tracker.compact(issue)
    if args.command == "update":
        return tracker.update(number, read_input(args.input), args.expected_hash)
    if args.command == "close" and issue["state"] == "closed":
        return {**tracker.compact(issue), "already_closed": True}
    text = "Linked work: " + args.target if args.command == "link" else Path(args.text_file).read_text(encoding="utf-8-sig")
    if args.command == "link" and not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(issues|pull)/[1-9][0-9]*", args.target):
        raise ItemError("link target must be a GitHub issue or pull request URL")
    comment = tracker.comment(number, text, args.request_id, args.command, getattr(args, "reconcile_only", False))
    if args.command == "close":
        try:
            return tracker.compact(api.request("PATCH", tracker.endpoint + f"/{number}", {"state": "closed", "state_reason": "completed"}))
        except APIError as error:
            raise ItemError("close outcome uncertain; read state before retrying with the same request-id") from error
    return {"identity": f"{tracker.repo}#{number}", "comment_url": comment["html_url"]}
