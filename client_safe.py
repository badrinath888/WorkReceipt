"""WorkReceipt Client-Safe Mode: allowlisted client report model, deny-by-default serialisation, approval tokens and final-artifact checks.

DESIGN RULES (read before changing anything here)
  * The client report is NOT the developer report with words removed. It is a separate model (ClientReport) whose fields are listed
    explicitly in PUBLIC_FIELDS / ITEM_FIELDS / VERIFICATION_FIELDS. Raw prompts, Git messages, commands, paths, URLs and logs have no
    code path into it: build_report() reads only the named keys of the draft the developer wrote and only counts from private evidence.
  * Unknown fields are dropped (and counted, never echoed). A dataclass that gained a field nobody approved here fails public().
  * Everything the developer types is screened (secrets, links, paths, file names, commit ids, commands, markup, private terms). A hit
    BLOCKS; text is never silently edited to make it pass.
  * Screening and artifact scanning are defence in depth. They are heuristics: they cannot know what is confidential to a client.
    The human reads the exact preview and approves it; approval is bound to the exact content (see approval_token).
  * This module never imports app_core (no cycle) and never logs or raises with report content: issues carry a field label and a
    code from MESSAGES, nothing else."""
import dataclasses, getpass, hashlib, hmac, json, re, secrets, socket, time, unicodedata
from dataclasses import dataclass, fields
from datetime import datetime
from html.parser import HTMLParser

import workreceipt as w

MAX_NAME, MAX_TEXT, MAX_VERIFY, MAX_ITEMS, MAX_COMMITS = 80, 400, 300, 40, 200
APPROVAL_TTL = 4 * 3600
STATUS_LABEL = {"delivered": "Delivered", "in_progress": "In progress"}
VERIFY_MODES = ("none", "auto", "custom")

# What the client report may contain. Nothing outside these tuples is ever serialised.
PUBLIC_FIELDS = ("project_name", "client_name", "prepared_by", "period", "report_date", "items", "verification")
ITEM_FIELDS = ("text", "status", "evidence", "n_commits")
VERIFICATION_FIELDS = ("mode", "text", "checks_total", "checks_ok")

# What the exported report never contains, shown to the person in the sharing review (kept here so UI and docs cannot drift).
EXCLUDED = ("Source code and diffs", "Your prompts and the AI's responses", "Terminal commands and their output", "Git commit messages and commit ids",
            "File names, folder names and file paths", "Repository addresses and any other links", "Passwords, keys, tokens and environment variables",
            "Server, database and infrastructure names", "Your computer's user name, machine name and device details",
            "Raw verification logs", "Anything you have not approved")

MESSAGES = {
    "required": "is required.", "too_long": "is too long.", "invalid": "contains characters that cannot be used.", "not_text": "must be plain text.",
    "secret": "looks like a credential, key, token, email address, IP address or private path. Remove it.",
    "url": "contains a link or web address. Client-safe reports do not include links.",
    "path": "contains a file or folder path.", "filename": "contains a source file name.", "hash": "contains a commit-id-like code.",
    "command": "looks like a terminal command or code.", "env": "contains an environment variable or configuration setting.",
    "markup": "contains HTML-like markup. Use plain text.", "private_term": "contains a term from your always-redact list.",
    "local_id": "contains a name that identifies this computer or account.",
    "status": "needs a valid status.", "evidence_missing": "is marked Delivered but has no evidence. Link Git commits or confirm it yourself.",
    "evidence_unknown": "refers to Git evidence that is no longer available. Reload the project and choose the commits again.",
    "no_items": "Approve at least one item before previewing.", "no_checks": "There are no recorded checks to summarise. Choose another option.",
    "too_many": "has too many entries.", "verify_mode": "needs a valid choice.",
}
FAILURE_TEXT = {"mismatch": "the file did not match the approved content", "markup": "unexpected markup", "attr": "unexpected attribute", "link": "a link or embedded resource",
                "source": "forbidden source content", "text": "text that is not part of the approved content", "secret": "sensitive-looking content",
                "metadata": "document metadata", "metadata_title": "a PDF title that is not the report title", "metadata_author": "a PDF author field", "metadata_subject": "a PDF subject field",
                "metadata_keywords": "PDF keywords", "metadata_creator": "a PDF creator field", "metadata_producer": "a PDF producer field", "annotation": "an annotation, attachment or script", "pdf_text": "extra or hidden text", "pdf_unreadable": "the PDF could not be read back",
                "pdf_unverified": "no way to verify the PDF on this computer", "filename": "an unsafe file name", "empty": "no readable text"}


class SchemaError(RuntimeError):
    """The internal model gained a field that was never approved for export."""


@dataclass(frozen=True)
class ClientItem:
    text: str
    status: str
    evidence: str          # "git" | "attested" | "none"
    n_commits: int


@dataclass(frozen=True)
class Verification:
    mode: str
    text: str
    checks_total: int
    checks_ok: int


@dataclass(frozen=True)
class ClientReport:
    project_name: str
    client_name: str
    prepared_by: str
    period: str
    report_date: str
    items: tuple
    verification: Verification


def _assert_schema(obj, expected):
    got = tuple(f.name for f in fields(obj))
    if got != expected:
        raise SchemaError("model fields are not on the export allowlist")


def public(r):
    """Deny-by-default serialisation: only allowlisted names, in a fixed order. Anything else on the object is ignored, and a model
    that gained an extra field raises instead of exporting it."""
    _assert_schema(r, PUBLIC_FIELDS)
    _assert_schema(r.verification, VERIFICATION_FIELDS)
    items = []
    for i in r.items:
        _assert_schema(i, ITEM_FIELDS)
        items.append({k: getattr(i, k) for k in ITEM_FIELDS})
    return {"project_name": r.project_name, "client_name": r.client_name, "prepared_by": r.prepared_by, "period": r.period,
            "report_date": r.report_date, "items": items, "verification": {k: getattr(r.verification, k) for k in VERIFICATION_FIELDS}}


def title_of(r):
    return f"Work report for {r.client_name}" if r.client_name else "Work report"


# ---------------------------------------------------------------- screening
class Issue(dict):
    def __init__(self, field, code):
        super().__init__(field=field, code=code, message=f"{field} {MESSAGES[code]}" if code not in ("no_items", "no_checks") else MESSAGES[code])


_URL = re.compile(r"(?i)(?:\b[a-z][a-z0-9+.-]{1,30}://|\bwww\.|\bgit@|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|dev|app|cloud|internal|local|corp|lan|ai|co|us|uk|in|edu|gov)\b(?:[/:?#]\S*)?)")
_PATH = re.compile(r"(?:(?<![\w.])(?:/(?:Users|home|var|etc|opt|usr|tmp|private|Volumes|mnt|srv|root|bin|dev|proc)\b[^\s]*)|(?<![\w.])~/[^\s]*|\b[A-Za-z]:\\[^\s]*|\\\\[\w.-]+\\[^\s]*)")
_EXT = r"py|pyc|js|jsx|mjs|ts|tsx|java|kt|go|rs|rb|php|c|cc|cpp|h|hpp|cs|swift|m|sql|sh|bash|zsh|yml|yaml|json|toml|ini|env|cfg|conf|lock|md|html|htm|css|scss|xml|plist|pem|key|crt|log|tf|gradle|dockerfile"
_FILE = re.compile(rf"(?i)(?<![\w@])(?:[\w.-]+/)*[\w-][\w.-]*\.(?:{_EXT})(?![\w])")
_FILE_OK = {"node.js", "next.js", "nuxt.js", "vue.js", "react.js", "express.js", "three.js", "d3.js", "chart.js", "nest.js", "ember.js", "backbone.js", "alpine.js", "p5.js", "socket.io"}
_SLASH_PATH = re.compile(r"(?<![\w/])(?:\.{0,2}/)?(?:[\w.-]+/){2,}[\w.-]+")
_DATEISH = re.compile(r"\d{1,4}(?:/\d{1,4}){1,2}")
_HASH = re.compile(r"(?i)(?<![\w])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![\w])")
_ENV = re.compile(r"(?:\b[A-Z][A-Z0-9_]{2,}\s*=\s*\S|\$\{?[A-Za-z_]\w*\}?|\bprocess\.env\b|\bos\.environ\b|\bexport\s+[A-Za-z_]\w*=)")
_CMD = re.compile(r"(?i)(?:^|[\s;&|])(?:\$\s|sudo\s+\w|npm\s+(?:run|install|i|test|ci|start|build|publish)\b|yarn\s+(?:add|install|run|build)\b|pnpm\s+\w|pip3?\s+install\b|docker\s+(?:run|build|compose|exec|push|pull|ps)\b|"
                  r"kubectl\s+\w|git\s+(?:clone|push|pull|commit|checkout|rebase|merge|reset|add|log|diff|status|stash)\b|curl\s+-|wget\s+\S|ssh\s+\S+@|scp\s+\S|chmod\s+\S|rm\s+-|python3?\s+\S+\.py|chown\s+\S)|```|`[^`]+`|\bdef\s+\w+\(|\bfunction\s+\w+\(|=>|\bimport\s+\w+\s+from\b|\bSELECT\b.+\bFROM\b")
_MARKUP = re.compile(r"(?i)<\s*/?\s*[a-z!?]|&#?\w+;|javascript\s*:|\bdata:[\w/+.-]+[;,]|\bon[a-z]{3,}\s*=")
_COMMON_USERS = {"root", "admin", "user", "test", "dev", "ubuntu", "guest", "runner", "build", "claude", "node", "app"}


def _norm(s):
    return unicodedata.normalize("NFKC", s)


def _squeeze(s):
    return re.sub(r"[\W_]+", "", _norm(s).casefold())


def local_identifiers():
    """This computer's account and machine names; they must never appear in a report. Common words (root, admin…) are skipped so
    ordinary prose is not blocked."""
    ids = set()
    try:
        ids.add(getpass.getuser())
    except Exception:                                                       # noqa: BLE001
        pass
    try:
        h = socket.gethostname()
        ids.update({h, h.split(".")[0]})
    except Exception:                                                       # noqa: BLE001
        pass
    return sorted({i for i in ids if i and len(i) >= 4 and i.casefold() not in _COMMON_USERS})


def screen(text, field, private_terms=(), local_ids=(), out=None):
    """Heuristic check of ONE piece of text. Returns a list of Issue (also appended to `out`). Never includes the text in an issue."""
    found = [] if out is None else out
    if not text:
        return found
    n = _norm(text)
    seen = set()

    def add(code):
        if code not in seen:
            seen.add(code)
            found.append(Issue(field, code))
    r = w.Redactor([])
    r(n)
    if r.hits:
        add("secret")
    if _URL.search(n):
        add("url")
    if _PATH.search(n):
        add("path")
    if any(m.group(0).casefold() not in _FILE_OK for m in _FILE.finditer(n)):
        add("filename")
    if any(not _DATEISH.fullmatch(m.group(0)) for m in _SLASH_PATH.finditer(n)):
        add("path")
    if _HASH.search(n):
        add("hash")
    if _ENV.search(n):
        add("env")
    if _CMD.search(n):
        add("command")
    if _MARKUP.search(n):
        add("markup")
    sq = _squeeze(n)
    if any(len(_squeeze(t)) >= 3 and _squeeze(t) in sq for t in private_terms):
        add("private_term")
    if any(_squeeze(i) in sq for i in local_ids if len(_squeeze(i)) >= 4):
        add("local_id")
    return found


def _clean(value, limit, field, issues, required=False):
    """Plain single-line text: hidden/control/format characters removed, whitespace collapsed, length enforced (never truncated)."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        issues.append(Issue(field, "not_text"))
        return ""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        issues.append(Issue(field, "invalid"))
        return ""
    s = unicodedata.normalize("NFC", value)
    s = "".join(c for c in s if unicodedata.category(c) not in ("Cc", "Cf", "Co", "Cs", "Cn") or c in " \t\n")
    s = re.sub(r"\s+", " ", s).strip()
    if required and not s:
        issues.append(Issue(field, "required"))
    if len(s) > limit:
        issues.append(Issue(field, "too_long"))
        return ""                                                           # never screen or keep an over-long text
    return s


def period_label(since, until):
    if since and until:
        return f"{since} to {until}"
    if until:
        return f"Up to {until}"
    if since:
        return f"From {since}"
    return "All available activity"


_DRAFT_KEYS = {"project_name", "client_name", "prepared_by", "include_prepared_by", "items", "verification"}
_ITEM_KEYS = {"id", "text", "status", "commits", "attested", "approved"}


def build_report(draft, evidence, period, private_terms=(), local_ids=None, today=None):
    """-> (ClientReport | None, issues, ignored_count).
    `draft` is what the developer wrote and approved in the UI. `evidence` is computed by the server from the private data:
    {"commits": set of full commit ids in the period, "checks_total": int, "checks_ok": int}. The draft can never supply counts."""
    issues = []
    d = draft if isinstance(draft, dict) else {}
    ignored = len(set(d) - _DRAFT_KEYS)
    lids = local_identifiers() if local_ids is None else local_ids
    pt = [t for t in private_terms if isinstance(t, str)]

    def text(key, limit, field, required=False):
        s = _clean(d.get(key), limit, field, issues, required)
        screen(s, field, pt, lids, issues)
        return s
    project = text("project_name", MAX_NAME, "Project name", True)
    client = text("client_name", MAX_NAME, "Client name")
    prepared = ""
    if d.get("include_prepared_by") is True:
        prepared = text("prepared_by", MAX_NAME, "Prepared by", True)
    items = []
    raw = d.get("items")
    if not isinstance(raw, list):
        raw = []
    if len(raw) > MAX_ITEMS:
        issues.append(Issue("Items", "too_many"))
        raw = raw[:MAX_ITEMS]
    known = evidence.get("commits") or set()
    n = 0
    for it in raw:
        if not isinstance(it, dict):
            continue
        ignored += len(set(it) - _ITEM_KEYS)
        if it.get("approved") is not True:                                  # unapproved entries never enter the model
            ignored += 1
            continue
        n += 1
        f = f"Item {n}"
        t = _clean(it.get("text"), MAX_TEXT, f, issues, True)
        screen(t, f, pt, lids, issues)
        st = it.get("status")
        if st not in STATUS_LABEL:
            issues.append(Issue(f, "status"))
            continue
        ev, nc = "none", 0
        if st == "delivered":
            cm = it.get("commits")
            if cm is not None and not isinstance(cm, list):
                issues.append(Issue(f, "evidence_unknown"))
            elif isinstance(cm, list) and cm:
                ids = {c for c in cm if isinstance(c, str)}
                if len(cm) > MAX_COMMITS or len(ids) != len(cm) or not ids <= known:
                    issues.append(Issue(f, "evidence_unknown"))
                else:
                    ev, nc = "git", len(ids)
            elif it.get("attested") is True:
                ev = "attested"
            else:
                issues.append(Issue(f, "evidence_missing"))
        items.append(ClientItem(t, st, ev, nc))
    if not items and not any(i["code"] == "too_many" for i in issues):
        issues.append(Issue("Items", "no_items"))
    v = d.get("verification") if isinstance(d.get("verification"), dict) else {}
    ignored += len(set(v) - {"mode", "text"})
    mode = v.get("mode", "none")
    vtext, total, ok = "", 0, 0
    if mode not in VERIFY_MODES:
        issues.append(Issue("Verification", "verify_mode"))
        mode = "none"
    elif mode == "auto":
        total, ok = int(evidence.get("checks_total") or 0), int(evidence.get("checks_ok") or 0)
        if total <= 0:
            issues.append(Issue("Verification", "no_checks"))
    elif mode == "custom":
        vtext = text_from(v.get("text"), MAX_VERIFY, "Verification", issues, pt, lids)
    if issues:
        return None, issues, ignored
    return ClientReport(project, client, prepared, period, (today or datetime.now()).strftime("%Y-%m-%d"), tuple(items), Verification(mode, vtext, total, ok)), [], ignored


def text_from(value, limit, field, issues, pt, lids):
    s = _clean(value, limit, field, issues, True)
    screen(s, field, pt, lids, issues)
    return s


# ---------------------------------------------------------------- approval
_SECRET = secrets.token_bytes(32)          # per process: a token can only be issued by this running app


def content_hash(r, scope):
    """Fingerprint of everything the approval covers: the exact content plus project, period and privacy-finding state."""
    blob = json.dumps({"report": public(r), "scope": scope}, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


def findings_fingerprint(pairs):
    """pairs: iterable of (detection id, disposition or ''). Any new finding or changed review changes the fingerprint."""
    return hashlib.sha256("|".join(sorted(f"{a}:{b}" for a, b in pairs)).encode()).hexdigest()[:16]


def approval_token(chash, now=None):
    ts = int(now if now is not None else time.time())
    return f"{ts}.{hmac.new(_SECRET, f'{ts}.{chash}'.encode(), hashlib.sha256).hexdigest()}"


def token_valid(token, chash, now=None):
    try:
        ts, sig = str(token).split(".", 1)
        age = (now if now is not None else time.time()) - int(ts)
    except (ValueError, TypeError):
        return False
    good = hmac.new(_SECRET, f"{ts}.{chash}".encode(), hashlib.sha256).hexdigest()
    return 0 <= age <= APPROVAL_TTL and hmac.compare_digest(good, sig)


# ---------------------------------------------------------------- rendering
# Same stylesheet as the developer report minus everything that edits or hides content, so the look stays consistent.
CLIENT_CSS = (w.CSS.replace("[contenteditable]{outline:1px dashed #c4cbd8;outline-offset:2px;border-radius:3px}", "")
              .replace("[contenteditable]{outline:none}.noprint{display:none}", ""))
CLIENT_FOOTER = ("@page{@bottom-left{content:'WorkReceipt work report';font:8pt sans-serif;color:#5b6676}"
                 "@bottom-right{content:'Page ' counter(page) ' of ' counter(pages);font:8pt sans-serif;color:#5b6676}}")
CSP = "default-src 'none'; style-src 'unsafe-inline'"
SOURCE_FORBIDDEN = ("<script", "<iframe", "<object", "<embed", "<link", "<img", "<svg", "<form", "<a ", "<a>", "<base", "<!--", "javascript:", "@import", "url(", "expression(", "data:image", "data:text", "data:application", "display:none", "visibility:hidden")
ALLOWED_TAGS = {"html", "meta", "title", "style", "div", "span", "h1", "h2", "p", "ul", "li", "table", "thead", "tbody", "tr", "th", "td", "b", "small", "br"}
ALLOWED_ATTRS = {"class", "lang", "charset", "name", "content", "http-equiv", "colspan"}
CLASSES = {"brand", "ident", "k", "v", "req", "no", "dt", "chip", "ok", "unk", "note", "small", "lead", "n", "sign", "keep", "foot", "stat", "stats"}
STATIC_INTRO = ("Each item below was written and approved by the preparer of this report. An item is marked Delivered only when it is supported by "
                "evidence in the project's version history, or when the preparer has confirmed it personally.")
STATIC_VERIFY = "These results were recorded by the development tools at the time. They were not re-run for this report."
STATIC_ABOUT = ("This report contains only information that the preparer reviewed and approved for sharing. It does not include source code, internal "
                "prompts, commit messages, file names or technical logs. Automatic checks help catch mistakes but cannot guarantee that nothing confidential "
                "remains, so the preparer is responsible for the content.")


def _evidence_label(i):
    if i.status != "delivered":
        return ""
    if i.evidence == "git":
        return f"Supported by Git history ({i.n_commits} commit{'s' if i.n_commits != 1 else ''})"
    return "Confirmed by the preparer"


def render_client(r):
    """The ONLY template for client artifacts. Input is a ClientReport; nothing else is in scope here."""
    e = w.esc
    public(r)                                                               # schema guard
    title = title_of(r)
    o = [f"<!doctype html><html lang=en><meta charset=utf-8><meta http-equiv=Content-Security-Policy content=\"{CSP}\">"
         f"<meta name=viewport content='width=device-width,initial-scale=1'><title>{e(title)}</title><style>{CLIENT_CSS}{CLIENT_FOOTER}</style>",
         "<div class=brand><b>WorkReceipt</b><span>Client work report</span></div>", f"<h1>{e(title)}</h1><div class=ident>",
         f"<div><span class=k>Project</span><span class=v>{e(r.project_name)}</span></div>"]
    if r.client_name:
        o.append(f"<div><span class=k>Client</span><span class=v>{e(r.client_name)}</span></div>")
    o.append(f"<div><span class=k>Period</span><span class=v>{e(r.period)}</span></div>")
    if r.prepared_by:
        o.append(f"<div><span class=k>Prepared by</span><span class=v>{e(r.prepared_by)}</span></div>")
    o.append(f"<div><span class=k>Report date</span><span class=v>{e(r.report_date)}</span></div></div>")
    o.append(f"<h2><span class=n>1</span>Work summary</h2><p class=lead>{e(STATIC_INTRO)}</p>")
    for n, i in enumerate(r.items, 1):
        cls, lab = ("ok", "Delivered") if i.status == "delivered" else ("unk", "In progress")
        ev = _evidence_label(i)
        note = f"<span class=note>{e(ev)}</span>" if ev else ""
        o.append(f"<div class=req><span class=no>{n}</span><span>{e(i.text)}{note}</span><span class='chip {cls}'>{lab}</span></div>")
    k = 2
    v = r.verification
    if v.mode != "none":
        o.append(f"<h2><span class=n>{k}</span>Verification</h2>")
        if v.mode == "auto":
            plural = "" if v.checks_total == 1 else "s"
            o.append(f"<p>{e(f'{v.checks_total} automated check{plural} recorded during this period; {v.checks_ok} finished without a reported error.')}</p>")
        else:
            o.append(f"<p>{e(v.text)}</p>")
        o.append(f"<p class='small keep'>{e(STATIC_VERIFY)}</p>")
        k += 1
    o.append(f"<h2><span class=n>{k}</span>About this report</h2><p class='small keep'>{e(STATIC_ABOUT)}</p>")
    o.append(f"<div class=sign><p>Reviewed and approved for sharing by: <b>{e(r.prepared_by) if r.prepared_by else 'the preparer of this report'}</b></p></div>")
    o.append("<div class=foot>Generated locally with WorkReceipt.</div>")
    return "".join(o)


# ---------------------------------------------------------------- final artifact checks
class _Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bad, self.text, self.attr_vals, self.style, self.title, self._in = set(), [], [], "", "", []

    def handle_decl(self, decl):
        if decl.strip().lower() != "doctype html":
            self.bad.add("markup")

    def handle_comment(self, data):
        self.bad.add("markup")

    def handle_pi(self, data):
        self.bad.add("markup")

    def unknown_decl(self, data):
        self.bad.add("markup")

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            self.bad.add("link" if tag in ("a", "img", "link", "iframe", "object", "embed", "script", "form", "svg", "base") else "markup")
        for k, val in attrs:
            if k not in ALLOWED_ATTRS:
                self.bad.add("link" if k in ("href", "src", "action", "srcset", "poster") else "attr")
                continue
            val = val or ""
            self.attr_vals.append(val)
            if k == "class" and not set(val.split()) <= CLASSES:
                self.bad.add("attr")
        if tag not in ("meta", "br"):
            self._in.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ("meta", "br") and self._in and self._in[-1] == tag:
            self._in.pop()

    def handle_endtag(self, tag):
        if self._in and self._in[-1] == tag:
            self._in.pop()

    def handle_data(self, data):
        cur = self._in[-1] if self._in else ""
        if cur == "style":
            self.style += data
        elif cur == "title":
            self.title += data
        elif data.strip():
            self.text.append(" ".join(data.split()))


def validate_html(html_text, r, private_terms=(), local_ids=None):
    """Checks the FINAL html string (as it will be written to disk). Returns a sorted list of failure codes; [] means it passed.
    Content is never included in the result."""
    bad = set()
    lids = local_identifiers() if local_ids is None else local_ids
    if html_text != render_client(r):
        bad.add("mismatch")
    low = html_text.lower()
    if any(s in low.replace(CLIENT_CSS.lower(), "").replace(CLIENT_FOOTER.lower(), "") for s in SOURCE_FORBIDDEN):
        bad.add("source")
    sc = _Scan()
    try:
        sc.feed(html_text)
        sc.close()
    except Exception:                                                       # noqa: BLE001
        bad.add("markup")
    bad |= sc.bad
    if sc.style != CLIENT_CSS + CLIENT_FOOTER:
        bad.add("source")
    if sc.title != title_of(r):
        bad.add("text")
    meta_ok = {"utf-8", CSP, "width=device-width,initial-scale=1", "viewport", "content-security-policy", "charset", "en"}
    if not {v.lower() for v in sc.attr_vals if v and not set(v.split()) <= CLASSES} <= meta_ok:
        bad.add("attr")
    pieces = sc.text + [sc.title]
    for p in pieces:
        if screen(p, "x", private_terms, lids):
            bad.add("secret")
    return sorted(bad)


def _tokens(s):
    return [t for t in (_squeeze(x) for x in _norm(s).split()) if t]


# Renderer self-description that Chrome/WebKit write into every PDF. It names the browser engine and OS family (never a user or machine name).
# Anything else in Creator/Producer fails. See docs/CLIENT_SAFE_MODE.md (remaining risks).
_PRODUCER_OK = re.compile(r"(?i)^(?:skia/pdf m?\d+|chrome(?:ium)?(?:/[\d.]+)?|quartz pdfcontext|macos version [\d.]+ \(build \w+\)(?: quartz pdfcontext)?|webkit|"
                          r"mozilla/5\.0 \([\w .;:,_-]{1,60}\) applewebkit/[\d.]+ \(khtml, like gecko\)[\w ./-]{0,60})$")
_PDF_FORBID = (b"/URI", b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/FileAttachment", b"/OpenAction", b"/GoToR", b"/SubmitForm", b"/RichMedia", b"/XFA", b"/AcroForm", b"/Names")
PDF_FOOTER_WORDS = {"workreceipt", "work", "report", "page", "of"}
# Some extractors (pypdf) join the footer's separate text runs without a space ("1" + "WorkReceipt" -> "1workreceipt"). A token made ONLY of
# page numbers and footer words is still footer text; anything else in it (or any other token) remains "extra text".
_FOOTER_TOKEN = re.compile(r"^(?:\d+|" + "|".join(sorted(PDF_FOOTER_WORDS, key=len, reverse=True)) + r")+$")


def _mentions(text, private_terms, local_ids):
    sq = _squeeze(text)
    return any(len(_squeeze(t)) >= 3 and _squeeze(t) in sq for t in private_terms) or any(len(_squeeze(i)) >= 4 and _squeeze(i) in sq for i in local_ids)


def pdf_metadata_problems(meta, title, private_terms=(), local_ids=()):
    """{field: reason} for every PDF information-dictionary field that is not allowed. Policy (unchanged, deliberately narrow):
    Title is empty or exactly the approved report title; Author, Subject and Keywords are empty; Creator and Producer may only
    name the rendering engine (_PRODUCER_OK); dates and Trapped are ignored; any other field must be empty; and NO field may mention a
    private term or this computer's account/machine name. Reasons are short codes, never the value."""
    out = {}
    for k, val in meta.items():
        k = str(k).lstrip("/")
        if k in ("CreationDate", "ModDate", "Trapped"):
            continue
        val = str(val or "")
        if k == "Title":
            if val not in ("", title):
                out[k] = "title_differs"
        elif k in ("Creator", "Producer"):
            if val.strip() and not _PRODUCER_OK.match(val.strip()):
                out[k] = "not_an_engine_string"
        elif val.strip():
            out[k] = "must_be_empty"
        if val and _mentions(val, private_terms, local_ids):
            out[k] = "mentions_private_or_local_name"
    return out


_INFO_REF = re.compile(rb"/Info\s+(\d+)\s+(\d+)\s+R")
_INFO_PAIR = re.compile(rb"/([A-Za-z][A-Za-z0-9_.+-]*)\s*(\((?:\\.|[^\\()]|\((?:\\.|[^\\()])*\))*\)|<[0-9A-Fa-f\s]*>)", re.S)
_ESC = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12, ord("("): 40, ord(")"): 41, ord("\\"): 92}


def _pdf_text_string(tok):
    """Decode a PDF literal (...) or hex <...> string the way a viewer shows it (UTF-16 with BOM, UTF-8 with BOM, else PDFDocEncoding ~ latin-1)."""
    if tok[:1] == b"<":
        h = re.sub(rb"\s", b"", tok[1:-1])
        raw = bytes.fromhex((h + (b"0" if len(h) % 2 else b"")).decode("ascii"))
    else:
        body, out, i = tok[1:-1], bytearray(), 0
        while i < len(body):
            c = body[i]
            if c != 92:
                out.append(c); i += 1; continue
            i += 1
            if i >= len(body):
                break
            c = body[i]
            if 48 <= c <= 55:
                j = i
                while j < len(body) and j < i + 3 and 48 <= body[j] <= 55:
                    j += 1
                out.append(int(body[i:j], 8) & 255); i = j; continue
            if c in _ESC:
                out.append(_ESC[c])
            elif c not in (10, 13):                       # backslash-newline is a line continuation; any other escape is the character itself
                out.append(c)
            i += 1
        raw = bytes(out)
    if raw[:2] == b"\xfe\xff":
        return raw[2:].decode("utf-16-be", "replace")
    if raw[:2] == b"\xff\xfe":
        return raw[2:].decode("utf-16-le", "replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", "replace")
    return raw.decode("latin-1")


def raw_info_fields(skeleton):
    """Fields of the PDF information dictionary read straight from the file bytes (`skeleton` = the file with stream bodies removed), NOT through
    whatever extractor produced `facts`. Defence in depth: a title or other field that the extractor drops, renames or filters out is still
    seen here. Returns {} when the dictionary is not a plain object (e.g. inside an object stream); the extractor's view then stands alone."""
    refs = _INFO_REF.findall(skeleton)
    if not refs:
        return {}
    n, g = refs[-1]
    heads = list(re.finditer(rb"(?<![0-9])" + n + rb"\s+" + g + rb"\s+obj\b", skeleton))
    if not heads:
        return {}
    start = heads[-1].end()
    end = skeleton.find(b"endobj", start)
    region = skeleton[start:end if end >= 0 else len(skeleton)]
    out = {}
    for m in _INFO_PAIR.finditer(region):
        try:
            out[m.group(1).decode("ascii")] = _pdf_text_string(m.group(2))
        except (ValueError, UnicodeError):
            out[m.group(1).decode("ascii")] = "\ufffd"        # undecodable value: present and not empty, so it is refused
    return out


def describe_pdf_metadata(meta, title, private_terms=(), local_ids=()):
    """Diagnostic text for the validation harness: allowed values are shown, anything else only as its length, so an account name is never echoed."""
    probs = pdf_metadata_problems(meta, title, private_terms, local_ids)
    parts = []
    for k, v in sorted((str(k).lstrip("/"), str(v or "")) for k, v in meta.items()):
        if k in ("CreationDate", "ModDate", "Trapped"):
            continue
        parts.append(f"{k}={'(empty)' if not v.strip() else (repr(v[:90]) if k not in probs else f'<{len(v)} chars, rejected: ' + probs[k] + '>')}")
    return "; ".join(parts) or "(no information dictionary)"


def validate_pdf(path, r, html_text, facts, private_terms=(), local_ids=None):
    """`facts` come from an extractor: {"text": str, "meta": {Title, Author, ...}, "annotations": int, "attachments": int} or None when no
    extractor could read the file. None, an unreadable file or anything unexpected FAILS: the check must complete to pass."""
    bad = set()
    lids = local_identifiers() if local_ids is None else local_ids
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return ["pdf_unreadable"]
    if len(data) < 100 or not data.startswith(b"%PDF-"):
        return ["pdf_unreadable"]
    skeleton = re.sub(rb"stream\r?\n.*?\r?\nendstream", b"", data, flags=re.S)          # compressed bytes can contain any 3 characters; only objects are read
    if any(tok in skeleton for tok in _PDF_FORBID):
        bad.add("annotation")
    if facts is None:
        return sorted(bad | {"pdf_unverified"})
    if facts.get("annotations") or facts.get("attachments"):
        bad.add("annotation")
    meta = {str(k).lstrip("/"): str(v or "") for k, v in (facts.get("meta") or {}).items()}
    probs = pdf_metadata_problems(meta, title_of(r), private_terms, lids)
    for field, why in pdf_metadata_problems(raw_info_fields(skeleton), title_of(r), private_terms, lids).items():      # second, extractor-independent read
        probs.setdefault(field, why)
    for field, why in probs.items():
        bad.add("metadata")
        bad.add("metadata_" + field.lower())                                 # field NAME only (never the value), so a refusal can be diagnosed
    text = facts.get("text")
    if not isinstance(text, str):
        return sorted(bad | {"pdf_unverified"})
    if not text.strip():
        return sorted(bad | {"empty"})
    sc = _Scan()
    sc.feed(html_text)
    vis = "".join(_squeeze(x) for x in sc.text + [sc.title])
    extra = [t for t in _tokens(text) if t not in vis and not _FOOTER_TOKEN.match(t)]
    if extra:
        bad.add("pdf_text")
    for line in text.splitlines():
        if line.strip() and screen(line, "x", private_terms, lids):
            bad.add("secret")
    return sorted(bad)


def pdf_facts_cli(path):
    """Linux/dev extractor: poppler's pdftotext/pdfinfo when installed, else pypdf, else None (-> validation cannot complete)."""
    import shutil, subprocess
    try:
        if shutil.which("pdftotext") and shutil.which("pdfinfo"):
            t = subprocess.run(["pdftotext", "-q", "-layout", path, "-"], capture_output=True, timeout=60)
            i = subprocess.run(["pdfinfo", "-isodates", path], capture_output=True, timeout=60)
            if t.returncode == 0 and i.returncode == 0:
                meta = {}
                for ln in i.stdout.decode("utf-8", "replace").splitlines():
                    k, _, v = ln.partition(":")
                    if k.strip() in ("Title", "Author", "Subject", "Keywords", "Creator", "Producer"):
                        meta[k.strip()] = v.strip()
                data = open(path, "rb").read()
                return {"text": t.stdout.decode("utf-8", "replace"), "meta": meta, "annotations": data.count(b"/Annots"), "attachments": data.count(b"/EmbeddedFile")}
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        import pypdf
        rd = pypdf.PdfReader(path)
        return {"text": "\n".join((p.extract_text() or "") for p in rd.pages), "meta": {k.lstrip("/"): v for k, v in (rd.metadata or {}).items()},
                "annotations": sum(len(p.get("/Annots") or []) for p in rd.pages), "attachments": len((rd.trailer["/Root"].get("/Names") or {}))}
    except Exception:                                                       # noqa: BLE001
        return None


def safe_basename(project_name, private_terms=(), local_ids=None):
    """Client-facing file name stem from the APPROVED display name only. Falls back to a neutral name if anything looks unsafe."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", unicodedata.normalize("NFKD", project_name).encode("ascii", "ignore").decode()).strip("-")[:40].strip("-")
    stem = f"client-report-{slug}" if slug else "client-report"
    if screen(stem.replace("-", " "), "x", private_terms, local_identifiers() if local_ids is None else local_ids):
        return "client-report"
    return stem
