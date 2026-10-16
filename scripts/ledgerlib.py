"""Shared helpers for the VectorSpace Infrastructure forecast ledger.

Imported by validate.py, score.py, build.py and archive.py. Nothing here
runs on its own.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import subprocess
from dataclasses import dataclass

import yaml

ID_RE = re.compile(r"^FCB-(\d{4})-(\d{3})$")
TAG_RE = re.compile(r"^(\d{4})-Q([1-4])$")

STATUSES = ("open", "flagged", "resolved_yes", "resolved_no", "void", "retracted")
LIVE_STATUSES = ("open", "flagged")
RESOLVED_STATUSES = ("resolved_yes", "resolved_no", "void", "retracted")
SCORED_STATUSES = ("resolved_yes", "resolved_no", "retracted")  # count in hit rate and Brier

STATUS_LABEL = {
    "open": "Open",
    "flagged": "Flagged",
    "resolved_yes": "Resolved YES",
    "resolved_no": "Resolved NO",
    "void": "Void",
    "retracted": "Retracted",
}
STATUS_GROUP = {
    "open": "open",
    "flagged": "flagged",
    "resolved_yes": "resolved",
    "resolved_no": "resolved",
    "retracted": "resolved",
    "void": "void",
}
# A retracted call scores as NO at its stated confidence (spec: a miss declared early).
RESULT_FOR_STATUS = {"resolved_yes": "YES", "resolved_no": "NO", "void": "VOID", "retracted": "NO"}

REQUIRED = (
    "id", "title", "claim", "made_on", "resolves_on", "resolution_rule", "confidence",
    "consensus_at_time", "thesis", "leading_indicators", "changes_my_mind", "implies_for", "status",
)
# Never editable after the file's first commit.
FROZEN = (
    "id", "title", "claim", "made_on", "resolves_on", "resolution_rule", "confidence",
    "consensus_at_time", "thesis", "leading_indicators", "changes_my_mind", "implies_for", "supersedes",
)
SET_ONCE = ("outcome", "score", "postmortem")
KNOWN_FIELDS = set(REQUIRED) | set(FROZEN) | set(SET_ONCE) | {"service", "updates"}


# --------------------------------------------------------------------------- paths

def repo_root(arg: str | None = None) -> pathlib.Path:
    """The ledger repository root: --root if given, else the parent of scripts/."""
    if arg:
        return pathlib.Path(arg).resolve()
    return pathlib.Path(__file__).resolve().parent.parent


def call_paths(root: pathlib.Path, include_examples: bool = False) -> list[pathlib.Path]:
    calls = root / "calls"
    if not calls.is_dir():
        return []
    paths = sorted(p for p in calls.glob("*.md") if include_examples or not p.name.startswith("_"))
    return paths


def rel(root: pathlib.Path, path: pathlib.Path) -> str:
    return path.resolve().relative_to(root).as_posix()


# --------------------------------------------------------------------------- front matter

def split_front_matter(text: str) -> tuple[dict, str, str]:
    """Return (meta, body, raw_front_matter_text)."""
    if not text.startswith("---"):
        raise ValueError("file does not start with a '---' front matter block")
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)(.*)$", text, re.S)
    if not m:
        raise ValueError("front matter block is not closed with '---'")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 2}" if mark else "the front matter"  # +2: the opening '---' is line 1
        problem = getattr(e, "problem", None) or "not valid YAML"
        raise ValueError(f"cannot be read at {where} ({problem}). Text with a colon followed by a space, "
                         "or starting with a quote or #, must be wrapped in double quotes") from None
    if not isinstance(meta, dict):
        raise ValueError("front matter is not a key: value mapping")
    return meta, m.group(2), m.group(1)


def normalize(v):
    """Make two parses of the same YAML comparable: dates to ISO strings, strings stripped."""
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return [normalize(x) for x in v]
    if isinstance(v, dict):
        return {k: normalize(x) for k, x in v.items()}
    return v


def to_date(v) -> dt.date:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str):
        return dt.date.fromisoformat(v.strip())
    raise ValueError(f"not a date: {v!r}")


def is_date(v) -> bool:
    try:
        to_date(v)
        return True
    except (ValueError, TypeError):
        return False


@dataclass
class Call:
    path: pathlib.Path
    rel: str
    id: str          # from the filename stem; validate.py checks it matches meta["id"]
    meta: dict
    body: str
    raw: str         # whole file text

    @property
    def status(self) -> str:
        return str(self.meta.get("status", "")).strip()

    @property
    def is_example(self) -> bool:
        return self.path.name.startswith("_")


def load_call(root: pathlib.Path, path: pathlib.Path) -> Call:
    text = path.read_text(encoding="utf-8")
    meta, body, _ = split_front_matter(text)
    return Call(path=path, rel=rel(root, path), id=path.stem, meta=meta, body=body, raw=text)


def load_calls(root: pathlib.Path, include_examples: bool = False) -> list[Call]:
    return [load_call(root, p) for p in call_paths(root, include_examples)]


def yes_no(v) -> str | None:
    """YES / NO / VOID from a value; a bare `YES` or `NO` is a boolean to YAML, so booleans count too."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "YES" if v else "NO"
    return str(v).strip().upper()


def score_result(meta: dict) -> str | None:
    """The YES/NO/VOID result recorded in `score`, whether written as a string or a mapping."""
    s = meta.get("score")
    if isinstance(s, dict):
        s = s.get("result")
    return yes_no(s)


def score_brier(meta: dict) -> float | None:
    s = meta.get("score")
    if isinstance(s, dict) and s.get("brier") is not None:
        return float(s["brier"])
    return None


def brier_contribution(confidence: int, result: str) -> float | None:
    """(p - o)^2 with p the stated confidence and o = 1 for YES, 0 for NO. VOID has no score."""
    if result not in ("YES", "NO"):
        return None
    p = confidence / 100.0
    o = 1.0 if result == "YES" else 0.0
    return round((p - o) ** 2, 6)


def is_hit(confidence: int, result: str) -> bool | None:
    """A hit is a YES called at 50% or more, or a NO called under 50%."""
    if result == "YES":
        return confidence >= 50
    if result == "NO":
        return confidence < 50
    return None


# --------------------------------------------------------------------------- git

class GitError(RuntimeError):
    pass


def git(root: pathlib.Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def is_git_repo(root: pathlib.Path) -> bool:
    try:
        return git(root, "rev-parse", "--is-inside-work-tree") == "true"
    except (GitError, FileNotFoundError):
        return False


def is_tracked(root: pathlib.Path, relpath: str) -> bool:
    return git(root, "ls-files", "--error-unmatch", relpath, check=False) != ""


def working_tree_differs(root: pathlib.Path, relpath: str) -> bool:
    proc = subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--", relpath])
    return proc.returncode != 0


def history(root: pathlib.Path, relpath: str) -> list[tuple[str, str]]:
    """All commits that touched the file, oldest first, as (sha, committer date YYYY-MM-DD)."""
    out = git(root, "log", "--reverse", "--format=%H %cs", "--", relpath)
    return [tuple(line.split(" ", 1)) for line in out.splitlines() if line.strip()]


def first_commit(root: pathlib.Path, relpath: str) -> tuple[str, str] | None:
    h = history(root, relpath)
    return h[0] if h else None


def file_at(root: pathlib.Path, sha: str, relpath: str) -> str | None:
    try:
        return git(root, "show", f"{sha}:{relpath}")
    except GitError:
        return None


def resolution_date(root: pathlib.Path, relpath: str) -> str | None:
    """Committer date of the first commit in which the file carried a resolved status."""
    for sha, date in history(root, relpath):
        text = file_at(root, sha, relpath)
        if not text:
            continue
        try:
            meta, _, _ = split_front_matter(text)
        except ValueError:
            continue
        if str(meta.get("status", "")).strip() in RESOLVED_STATUSES:
            return date
    return None


def latest_quarter_tag(root: pathlib.Path) -> tuple[str, str] | None:
    """Newest tag named YYYY-Qn, as (tag, date YYYY-MM-DD)."""
    out = git(root, "for-each-ref", "--sort=-creatordate",
              "--format=%(refname:short) %(creatordate:short)", "refs/tags", check=False)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and TAG_RE.match(parts[0]):
            return parts[0], parts[1]
    return None


def quarter_bounds(tag: str) -> tuple[dt.date, dt.date]:
    y, q = TAG_RE.match(tag).groups()
    y, q = int(y), int(q)
    start = dt.date(y, 3 * (q - 1) + 1, 1)
    end = dt.date(y + (q == 4), (3 * q) % 12 + 1, 1) - dt.timedelta(days=1)
    return start, end
