"""Repository contract v1 checks that are decidable from the caller's Git tree.

Parameters (limits, required PR sections, forbidden patterns, shared library
names) come from `schemas/repo-contract-v1.json` in this same shared-ci checkout,
so documentation, schema and checker cannot drift apart. Every finding uses the
schema-1 finding shape with layer `contract` and kind `contract_<item>`.
Items 3 and 5 are partly enforced elsewhere (workflow-lint, ruleset readback).
"""

from __future__ import annotations

import html
import json
import pathlib
import re
import stat
import subprocess
import unicodedata
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote

HERE = pathlib.Path(__file__).resolve().parent
CONTRACT_FILE = HERE.parents[1] / "schemas" / "repo-contract-v1.json"
SHA = re.compile(r"^[0-9a-f]{40}$")
USES = re.compile(r"""^\s*-?\s*uses:\s*["']?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/([^@\s"']+)@([^\s"'#]+)""")
POINTER = re.compile(
    r"(?:github\.com/LeePepe/shared-ci/blob/|LeePepe/shared-ci@)([0-9A-Za-z._/-]+?)/ai/agent-protocol\.md",
    re.IGNORECASE)
METADATA = ".github/repo-contract.json"
ROUTE = re.compile(r"^\s*(?:(?:[-*]|\d+\.)\s+)?(?:[^`\[\]<>:]+:\s*)?\[[^\[\]]+\]\(([^\s)]+)\)[.;]?\s*$")
INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")


def load_contract() -> dict[str, Any]:
    data = json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))
    return data["x-contract"]


def _git_files(root: pathlib.Path) -> dict[str, str]:
    """Tracked path -> git mode (e.g. 100644, 100755, 120000)."""
    result = subprocess.run(["git", "ls-files", "--stage", "-z"], cwd=root,
                            capture_output=True, check=False)
    if result.returncode != 0:
        return {}
    files = {}
    for item in result.stdout.split(b"\0"):
        if not item:
            continue
        meta, _, path = item.partition(b"\t")
        mode, _, stage = meta.split(b" ")
        files[path.decode("utf-8", errors="surrogateescape")] = mode.decode() if stage == b"0" else ""
    return files


def _text(root: pathlib.Path, path: str, limit: int = 2_000_000) -> str | None:
    if not _local_path(path):
        return None
    target = root
    try:
        # Check each component before reading: even an internal ancestor alias
        # can turn a tracked pathname into unrelated local or outside content.
        parts = path.split("/")
        for index, part in enumerate(parts):
            target = target / part
            info = target.lstat()
            regular = stat.S_ISREG(info.st_mode) if index == len(parts) - 1 else stat.S_ISDIR(info.st_mode)
            if not regular:
                return None
        if info.st_size > limit:
            return None
        raw = target.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:8192]:
        return None
    return raw.decode("utf-8", errors="replace")


def _tracked_text(root: pathlib.Path, path: str, files: dict) -> str | None:
    if files.get(path) not in ("100644", "100755"):
        return None
    return _text(root, path)


def section(markdown: str, title: str) -> str | None:
    """Body of the `## title` section (case-insensitive prefix match), else None."""
    lines = markdown.splitlines()
    wanted = title.strip().lower()
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,3})\s+(.*?)\s*#*\s*$", line)
        if match and match.group(2).strip().lower().startswith(wanted):
            level = len(match.group(1))
            body = []
            for following in lines[index + 1:]:
                heading = re.match(r"^(#{1,6})\s", following)
                if heading and len(heading.group(1)) <= level:
                    break
                body.append(following)
            return "\n".join(body)
    return None


def workflow_refs(root: pathlib.Path, files: dict[str, str]) -> list[tuple[str, int, str, str]]:
    """(file, line, path, ref) for every `uses: LeePepe/shared-ci/...@ref`."""
    refs = []
    for path in sorted(files):
        if not re.match(r"^\.github/workflows/[^/]+\.ya?ml$", path):
            continue
        text = _text(root, path) or ""
        for number, line in enumerate(text.splitlines(), 1):
            match = USES.match(line)
            if match and match.group(1).lower() == "leepepe" and match.group(2).lower() == "shared-ci":
                refs.append((path, number, match.group(3), match.group(4)))
    return refs


class _Report:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.findings: list[Any] = []

    def add(self, item: str, path: str, detail: str) -> None:
        self.findings.append(self.ctx.Finding("contract", path, "contract_" + item, detail))


def _local_path(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and not value.startswith("/") and "\\" not in value and not any(
        ord(char) < 32 or ord(char) == 127 for char in value) and all(
        part not in ("", ".", "..") for part in value.split("/"))


def _metadata(report: _Report, root: pathlib.Path, files: dict) -> dict | None:
    if (METADATA not in files and not (root / METADATA).exists()
            and not (root / METADATA).is_symlink() and not (root / ".github").is_symlink()):
        return None  # Legacy v1 callers retain their pinned AGENTS contract.
    if METADATA not in files:
        report.add("agents", METADATA, "repository metadata must be tracked")
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate key {key!r}")
                result[key] = value
            return result
        data = json.loads(_tracked_text(root, METADATA, files) or "", object_pairs_hook=unique)
        if not isinstance(data, dict) or set(data) != {"schema", "guide", "shared_ci", "dependencies"}:
            raise ValueError("expected schema, guide, shared_ci and dependencies")
        if type(data["schema"]) is not int or data["schema"] != 1:
            raise ValueError("metadata schema must be 1")
        if not isinstance(data["shared_ci"], str) or not SHA.fullmatch(data["shared_ci"]):
            raise ValueError("shared_ci must be a full 40-char SHA")
        if not _local_path(data["guide"]):
            raise ValueError("guide must be a repository-relative file path")
        if _tracked_text(root, data["guide"], files) is None:
            raise ValueError("guide must name a tracked readable regular file without symlinks")
        if not isinstance(data["dependencies"], dict):
            raise ValueError("dependencies must be an object")
        for name, item in data["dependencies"].items():
            if name.lower() == "shared-ci":
                raise ValueError("shared-ci is declared only by shared_ci, not duplicated in dependencies")
            if not isinstance(item, dict) or set(item) != {"version", "ai"}:
                raise ValueError(f"{name}: expected version and ai")
            version, url = item["version"], item["ai"]
            if not isinstance(version, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|v?\d+\.\d+\.\d+(?:[-+][\w.-]+)?)", version):
                raise ValueError(f"{name}: version must be exact semver or a full SHA")
            if not isinstance(url, str) or not url.startswith("https://") or not re.search(
                    r"/" + re.escape(version) + r"/ai/", url):
                raise ValueError(f"{name}: ai must point to that version's ai/ docs")
        return data
    except (ValueError, TypeError) as error:
        report.add("agents", METADATA, f"invalid repository metadata: {error}")
        return {}  # Invalid new metadata never silently falls back to AGENTS.


class _ExplicitAnchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        for name, value in attrs:
            if value and (name == "id" or (tag == "a" and name == "name")):
                self.anchors.add(value)


def _markdown_anchors(text: str) -> set[str]:
    """Block ATX/Setext headings and explicit HTML anchors, not a Markdown renderer."""
    headings: set[str] = set()
    explicit = _ExplicitAnchors()
    paragraph: list[str] = []
    visible: list[str] = []
    fence = ""
    html_block = False
    comment = False

    def heading(value: str) -> None:
        value = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", value)
        value = re.sub(r"<[^>]*>", "", value)
        value = re.sub(r"(?<!\w)(_+)(?=\S)(.+?)(?<=\S)\1(?!\w)", r"\2", value)
        value = html.unescape(value).lower()
        slug = "".join("-" if char.isspace() else char for char in value
                       if char.isspace() or char in "_-" or unicodedata.category(char)[0] in "LNM")
        unique, suffix = slug, 0
        while unique in headings:
            suffix += 1
            unique = f"{slug}-{suffix}"
        headings.add(unique)

    text = re.sub(r"\A---[^\S\n]*\n.*?\n(?:---|\.\.\.)[^\S\n]*(?:\n|$)", "", text, flags=re.DOTALL)
    for line in text.splitlines():
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line):
                fence = ""
            continue
        if not comment and line.startswith(("    ", "\t")):
            paragraph = []
            continue
        # Code examples and escaped HTML are displayed text, not HTML syntax.
        # Encode before comment/markup processing and decode only for the slug.
        line = INLINE_CODE.sub(lambda match: "".join(f"&#{ord(char)};" for char in match.group(2)), line)
        line = re.sub(r"\\([<>])", lambda match: html.escape(match.group(1)), line)
        if comment:
            _, end, line = line.partition("-->")
            if not end:
                continue
            comment = False
        line = re.sub(r"<!--.*?-->", "", line)
        if "<!--" in line:
            line = line.partition("<!--")[0]
            comment = True
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if opening:
            fence = opening.group(1)
            paragraph = []
            continue
        visible.append(line)
        if re.match(r"^ {0,3}</?[A-Za-z][\w-]*(?:\s|/?>)", line):
            html_block = True
        if html_block:
            html_block = bool(line.strip())
            paragraph = []
            continue
        atx = re.match(r"^ {0,3}#{1,6}(?:[ \t]+(.*?)|)[ \t]*$", line)
        if atx:
            heading(re.sub(r"[ \t]+#+[ \t]*$", "", atx.group(1) or "").strip())
            paragraph = []
        elif paragraph and re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", line):
            heading(" ".join(paragraph))
            paragraph = []
        elif not line.strip() or re.match(r"^ {0,3}(?:<|>|[-*+]\s|\d+[.)]\s)", line):
            paragraph = []
        else:
            paragraph.append(line.strip())
    explicit.feed("\n".join(visible))
    explicit.close()
    return headings | explicit.anchors


def _local_route(target: str) -> tuple[str, str | None]:
    """Decode once, then validate repository path syntax before any file access."""
    path, marker, fragment = target.partition("#")
    if "?" in path or ":" in path or re.search(r"%(?![0-9A-Fa-f]{2})", target):
        raise ValueError("malformed local route")
    path = unquote(path, errors="strict") if path else "AGENTS.md"
    fragment = unquote(fragment, errors="strict") if marker else None
    if not _local_path(path) or (fragment is not None and (not fragment or any(
            ord(char) < 32 or ord(char) == 127 for char in fragment))):
        raise ValueError("malformed local route")
    return path, fragment


def _index_agents(report: _Report, root: pathlib.Path, text: str, metadata: dict, refs: list, files: dict) -> None:
    routes = []
    local_paths = set()
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or re.match(r"^#{1,6}\s+", line):
            continue
        match = ROUTE.fullmatch(line)
        if not match:
            report.add("agents", f"AGENTS.md:{number}", "index-only AGENTS permits headings and conditional Markdown links, not inline instructions")
            continue
        target = match.group(1)
        routes.append(target)
        if target.startswith("https://"):
            continue
        try:
            path, fragment = _local_route(target)
        except ValueError:
            report.add("agents", f"AGENTS.md:{number}", f"malformed local route: {target}")
            continue
        document = _tracked_text(root, path, files)
        if document is None:
            report.add("agents", f"AGENTS.md:{number}", f"route target is not a tracked readable regular repository file without symlinks: {target}")
            continue
        local_paths.add(path)
        if fragment is not None and (pathlib.PurePosixPath(path).suffix.lower() not in (".md", ".markdown")
                                     or fragment not in _markdown_anchors(document)):
            report.add("agents", f"AGENTS.md:{number}", f"route fragment does not resolve to a Markdown anchor: {target}")
    if not routes:
        report.add("agents", "AGENTS.md", "index must route to repository documents")
    guide = metadata.get("guide")
    if guide and guide not in local_paths:
        report.add("agents", "AGENTS.md", f"index must route to the repository guide: {guide}")
    pin = metadata.get("shared_ci")
    caller = {ref for _, _, _, ref in refs}
    if pin and caller and caller != {pin}:
        report.add("agents", METADATA, f"shared_ci {pin} differs from workflow pins {sorted(caller)}")
    pointers = set(POINTER.findall(text))
    if pointers and pin and pointers != {pin}:
        report.add("agents", "AGENTS.md", "versioned protocol route differs from metadata shared_ci pin")


def _agents(report: _Report, root: pathlib.Path, contract: dict, refs: list, metadata: dict | None, files: dict) -> str:
    text = _tracked_text(root, "AGENTS.md", files) if metadata is not None else _text(root, "AGENTS.md")
    if text is None:
        report.add("agents", "AGENTS.md", "AGENTS.md is missing")
        return ""
    limit = contract["agents_max_lines"]
    count = len(text.splitlines())
    if count > limit:
        report.add("agents", "AGENTS.md", f"{count} lines exceeds {limit}")
    if metadata is not None:
        _index_agents(report, root, text, metadata, refs, files)
        return text
    pointers = POINTER.findall(text)
    if not pointers:
        report.add("agents", "AGENTS.md", "missing protocol pointer to shared-ci@<40-char SHA>/ai/agent-protocol.md")
    for pointer in pointers:
        if not SHA.match(pointer):
            report.add("agents", "AGENTS.md", f"protocol pointer {pointer!r} is not a full 40-char SHA")
    caller = {ref for _, _, _, ref in refs}
    if pointers and caller and set(pointers) != caller:
        report.add("agents", "AGENTS.md",
                   f"protocol pointer {sorted(set(pointers))} differs from workflow pins {sorted(caller)}")
    for title in contract["agents_sections"]:
        if section(text, title) is None:
            report.add("agents", "AGENTS.md", f"missing section '## {title}'")
    return text


def _required_checks(agents: str) -> list[str]:
    body = section(agents, "Required checks") or ""
    return [name for name in re.findall(r"`([^`]+)`", body) if name.strip()]


def _agent_files(report: _Report, root: pathlib.Path, contract: dict, agents: str) -> None:
    checks = _required_checks(agents)
    for path in contract["agent_files"]:
        text = _text(root, path)
        if text is None:
            continue
        if "AGENTS.md" not in text:
            report.add("agent_files", path, "must defer to AGENTS.md")
        count = len([line for line in text.splitlines() if line.strip()])
        if count > contract["agent_file_max_lines"]:
            report.add("agent_files", path, f"{count} non-empty lines; keep tool-specific notes only")
        if POINTER.search(text) or re.search(r"shared-ci[^\n]*@[0-9a-f]{40}", text):
            report.add("agent_files", path, "duplicates the shared-ci pin; use repository metadata (legacy: AGENTS.md)")
        for name in checks:
            if f"`{name}`" in text:
                report.add("agent_files", path, f"duplicates required check {name!r} from AGENTS.md")


def _ci(report: _Report, root: pathlib.Path, files: dict, refs: list) -> None:
    ci_files = [p for p in (".github/workflows/ci.yml", ".github/workflows/ci.yaml") if p in files]
    if not ci_files:
        report.add("ci", ".github/workflows/ci.yml", "caller workflow is missing")
    elif not any(file in ci_files and path == ".github/workflows/quality.yml" for file, _, path, _ in refs):
        report.add("ci", ci_files[0], "does not call LeePepe/shared-ci/.github/workflows/quality.yml")
    for file in ci_files:
        job = _quality_job(root, file)
        if job is not None and job != "quality":
            report.add("ci", file, f"job {job!r} calls quality.yml; name it 'quality' so the "
                                   "required check is 'quality / aggregate'")
    for file, line, path, ref in refs:
        if not SHA.match(ref):
            report.add("ci", f"{file}:{line}", f"{path}@{ref} is not pinned to a full 40-char SHA")
    if len({ref for *_, ref in refs}) > 1:
        report.add("ci", ".github/workflows", f"mixed shared-ci pins: {sorted({r for *_, r in refs})}")


def _quality_job(root: pathlib.Path, path: str) -> str | None:
    """Job id that calls shared-ci quality.yml, or None when not determinable."""
    try:
        data = _frontmatter().parse(_text(root, path) or "")
    except ValueError:
        return None
    jobs = data.get("jobs") if isinstance(data, dict) else None
    for job_id, job in (jobs or {}).items():
        uses = job.get("uses", "") if isinstance(job, dict) else ""
        if isinstance(uses, str) and re.match(r"(?i)^leepepe/shared-ci/\.github/workflows/quality\.ya?ml@", uses):
            return str(job_id)
    return None


def _review_rules(report: _Report, root: pathlib.Path, refs: list, metadata: dict | None) -> None:
    if not metadata:
        return
    paths = {path for path, _, workflow, _ in refs
             if workflow in (".github/workflows/codex-review.yml", ".github/workflows/kimi-review.yml")}
    for path in paths:
        try:
            data = _frontmatter().parse(_text(root, path) or "")
            jobs = data.get("jobs", {})
            for job in jobs.values():
                uses = job.get("uses", "") if isinstance(job, dict) else ""
                if re.search(r"(?i)^LeePepe/shared-ci/\.github/workflows/(codex|kimi)-review\.yml@", str(uses)):
                    if (job.get("with") or {}).get("rules-file") != metadata["guide"]:
                        report.add("ci", path, "index-only callers must set review rules-file to the repository guide")
        except (ValueError, AttributeError, TypeError):
            report.add("ci", path, "cannot resolve review rules-file from workflow")


def _frontmatter() -> Any:
    import importlib.util
    spec = importlib.util.spec_from_file_location("shared_ci_frontmatter", HERE / "_frontmatter.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verify(report: _Report, root: pathlib.Path, files: dict) -> None:
    if files.get("scripts/verify") != "100755":
        report.add("verify", "scripts/verify", "scripts/verify must be tracked and executable")
    hooks = [p for p in (".githooks/pre-push", ".githooks/pre-commit") if p in files]
    if not hooks:
        report.add("verify", ".githooks/pre-push", "no .githooks/pre-push or pre-commit hook")
    elif not any("scripts/verify" in (_text(root, hook) or "") for hook in hooks):
        report.add("verify", hooks[0], "hooks do not invoke scripts/verify")
    for hook in hooks:
        if files[hook] != "100755":
            report.add("verify", hook, "hook must be executable")
    workflows = [p for p in files if re.match(r"^\.github/workflows/ci\.ya?ml$", p)]
    if workflows and not any("scripts/verify" in (_text(root, p) or "") for p in workflows):
        report.add("verify", workflows[0], "CI does not invoke scripts/verify")


def _owner_pattern(pattern: str, path: str) -> bool:
    if pattern.startswith("!") or any(char in pattern for char in "\\[]"):
        raise ValueError("unsupported CODEOWNERS pattern")
    anchored = pattern.startswith("/") or "/" in pattern.rstrip("/")
    body, regex, index = pattern.strip("/"), "", 0
    while index < len(body):
        if body.startswith("**/", index) and (index == 0 or body[index - 1] == "/"):
            regex += "(?:[^/]+/)*"
            index += 3
        elif body[index:] == "**" and (index == 0 or body[index - 1] == "/"):
            regex += ".*"
            index += 2
        elif body[index] == "*":
            regex += "[^/]*"
            while index < len(body) and body[index] == "*":
                index += 1
        elif body[index] == "?":
            regex += "[^/]"
            index += 1
        else:
            regex += re.escape(body[index])
            index += 1
    regex = ("^" if anchored else "^(?:.*/)?") + regex + ("/.*$" if pattern.endswith("/") else "(?:/.*)?$")
    return re.match(regex, path) is not None


def _codeowners(report: _Report, root: pathlib.Path, files: dict, contract: dict, metadata: dict | None) -> None:
    owners = [p for p in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS") if p in files]
    if not owners:
        report.add("ruleset", ".github/CODEOWNERS", "CODEOWNERS is missing (review gate for important paths)")
        return
    patterns = {line.split()[0] for line in (_text(root, owners[0]) or "").splitlines()
                if line.strip() and not line.lstrip().startswith("#")}
    required_paths = list(contract["codeowners_required"])
    if metadata:
        required_paths.append("/" + metadata["guide"])
    for required in required_paths:
        if required not in patterns:
            report.add("ruleset", owners[0], f"CODEOWNERS does not cover {required}")
    if metadata:
        rules = [line.split("#", 1)[0].split() for line in (_text(root, owners[0]) or "").splitlines()]
        try:
            for path in ("AGENTS.md", METADATA, metadata["guide"]):
                last = []
                for parts in rules:
                    if parts and _owner_pattern(parts[0], path):
                        last = parts[1:]
                if not last:
                    report.add("ruleset", owners[0], f"CODEOWNERS leaves protected document unowned: {path}")
        except ValueError as error:
            report.add("ruleset", owners[0], f"cannot verify protected document ownership: {error}")


def _pr_template(report: _Report, root: pathlib.Path, files: dict, contract: dict) -> None:
    names = [p for p in files if p.lower() in (".github/pull_request_template.md",
                                                 "pull_request_template.md",
                                                 "docs/pull_request_template.md")]
    if not names:
        report.add("pr_template", ".github/pull_request_template.md", "PR template is missing")
        return
    text = _text(root, names[0]) or ""
    for title in contract["pr_sections"]:
        if section(text, title) is None:
            report.add("pr_template", names[0], f"missing required section '## {title}'")


def _resolved_pins(report: _Report, root: pathlib.Path, files: dict) -> dict[str, set[str]]:
    pins: dict[str, set[str]] = {}
    for path in files:
        name = pathlib.PurePosixPath(path).name
        if name not in ("Package.resolved", "package-lock.json"):
            continue
        text = _text(root, path)
        if text is None:
            # A denied alias/read must not erase a dependency pin from parity.
            report.add("dependencies", path, "cannot safely read tracked dependency lockfile")
            continue
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if name == "Package.resolved":
            for pin in data.get("pins", data.get("object", {}).get("pins", [])):
                identity = str(pin.get("identity") or pin.get("package") or "").lower()
                state = pin.get("state", {})
                pins.setdefault(identity, set()).update(
                    str(v) for v in (state.get("version"), state.get("revision")) if v)
        else:
            for key, info in (data.get("packages") or {}).items():
                if key.startswith("node_modules/") and isinstance(info, dict) and info.get("version"):
                    pins.setdefault(key.rsplit("/", 1)[-1].lower(), set()).add(str(info["version"]))
    return pins


def _dependencies(report: _Report, root: pathlib.Path, files: dict, contract: dict, agents: str,
                  metadata: dict | None) -> None:
    declared: dict[str, str] = {}
    source = METADATA if metadata is not None else "AGENTS.md"
    if metadata:
        declared = {name.lower(): item["version"] for name, item in metadata["dependencies"].items()}
        declared["shared-ci"] = metadata["shared_ci"]
    body = (section(agents, "Dependencies") or "") if metadata is None else ""
    for line in body.splitlines():
        match = re.match(r"^\s*[-*]\s+`?([A-Za-z0-9_.-]+)`?\s+`?([A-Za-z0-9_.+-]+)`?(.*)$", line)
        if not match or match.group(1).lower() not in contract["shared_libraries"]:
            continue
        name, version, rest = match.group(1).lower(), match.group(2), match.group(3)
        declared[name] = version
        if not re.search(r"[@/]" + re.escape(version) + r"/ai/", rest):
            report.add("dependencies", source, f"{name} {version} must point to that version's ai/ docs")
    pins = _resolved_pins(report, root, files)
    for name in contract["shared_libraries"]:
        observed = pins.get(name, set())
        if name in declared and observed and declared[name] not in observed:
            report.add("dependencies", source,
                       f"{name} declared {declared[name]} but lockfile pins {sorted(observed)}")
        if observed and name not in declared:
            report.add("dependencies", source, f"{name} is pinned in a lockfile but not declared")


def _identity(report: _Report, root: pathlib.Path, files: dict, contract: dict) -> None:
    # Regexes are written so that their own source text never matches them;
    # shared-ci can therefore apply the same check to itself.
    patterns = [(entry["name"], re.compile(entry["regex"])) for entry in contract["forbidden_patterns"]]
    for path in sorted(files):
        if files[path] == "120000":
            continue
        text = _text(root, path)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for name, pattern in patterns:
                if pattern.search(line):
                    report.add("identity", f"{path}:{number}",
                               f"forbidden personal identity or local path pattern: {name}")


def audit(ctx: Any, root: pathlib.Path) -> list[Any]:
    contract = load_contract()
    report = _Report(ctx)
    files = _git_files(root)
    refs = workflow_refs(root, files)
    metadata = _metadata(report, root, files)
    agents = _agents(report, root, contract, refs, metadata, files)
    guide = (_text(root, metadata["guide"]) or "") if metadata else agents
    if metadata:
        for title in contract["guide_sections"]:
            if section(guide, title) is None:
                report.add("agents", metadata["guide"], f"guide is missing section '## {title}'")
    _agent_files(report, root, contract, guide)
    _ci(report, root, files, refs)
    _review_rules(report, root, refs, metadata)
    _verify(report, root, files)
    _codeowners(report, root, files, contract, metadata)
    _pr_template(report, root, files, contract)
    _dependencies(report, root, files, contract, agents, metadata)
    _identity(report, root, files, contract)
    return report.findings
