"""
PHI redaction for EMR AutoMate
==============================
Makes debug artifacts and console output safe to share (with an AI assistant, a
coworker, a bug report) by construction.

WHY ALLOWLIST, NOT DENYLIST
    The obvious approach — "strip out the employee names we know about" — does not
    work here. The EMR dashboard preloads the ENTIRE worksite roster into
    .employee-list, so a captured page contains every employee, not just the one
    being worked on. There is no list of names to subtract.

    So we invert it: a piece of text survives only if it is a known-safe EMR UI
    string (a field label, a dropdown option, a button caption). Anything we do not
    recognise is replaced with a placeholder. A name, a date of birth, an employee
    ID, a free-text clinical note — none of them are in the vocabulary, so none of
    them can get through, including ones we have never seen.

    The cost is that a genuinely-safe UI label we forgot to register also gets
    redacted. That is the right side to fail on: you notice a missing label in a
    debug capture and add it to the vocabulary; you do not notice a leaked name.

WHAT IT COVERS
    scrub_html()   — page HTML: text nodes, attributes, comments, <script>/<style>
    screenshot_masks() — locators to paint over before a screenshot is taken
    ph() / pd()    — console output: employee names → "Employee #1", free text → a
                     character count. Only active when EMR_REDACT_CONSOLE=1, so your
                     own runs still read normally.

USAGE
    import phi_redact
    phi_redact.register_vocab(["Safety Coaching", ...])   # known-safe UI strings
    safe = phi_redact.scrub_html(await page.content())
    print(f"Locating {phi_redact.ph(full_name)}")
"""

import html as html_mod
import json
import os
import re
import sys
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
FIELD_OPTIONS_JSON = os.path.join(HERE, "emr_field_options.json")

# Turn console redaction on for a run:  set EMR_REDACT_CONSOLE=1
# Off by default so your own interactive runs still show real names.
ENV_FLAG = "EMR_REDACT_CONSOLE"


# ─────────────────────────────────────────────
# VOCABULARY — the only text allowed to survive
# ─────────────────────────────────────────────

# Static EMR/browser chrome. Everything here is a fixed UI string with no patient
# data in it. Add to this list when a redacted capture hides a label you needed.
UI_CHROME = [
    # App chrome / nav
    "ATI", "ATI Worksite Solutions", "Worksite", "Home", "Dashboard", "Menu",
    "Log In", "Login", "Log Out", "Logout", "Sign In", "Sign Out", "Profile",
    "Employees", "Employee", "Cases", "Case", "Encounters", "Encounter",
    "InProgress", "In Progress", "Completed", "Draft", "Drafts",
    # Buttons / actions
    "Save", "Save in progress", "Submit", "Cancel", "Close", "Next", "Back",
    "Previous", "Apply", "Clear", "Search", "Add", "Add Case", "+ Add Case",
    "Edit", "Delete", "Remove", "Select", "Select...", "OK", "Yes", "No",
    "Continue", "Confirm", "Loading", "Loading...", "Please wait",
    # Form labels / placeholders used by the automation
    "Coaching Encounter", "Coaching Type", "CoachingType",
    "Date of Encounter", "Search Employee or Identifier",
    "Department", "Division", "Category", "Shift",
    "What Prompted Coaching", "Description", "Details", "Encounter Type",
    "Assessment", "Assessment Type", "Type", "Name", "Date", "Status", "Actions",
    # Case-type tiles in the "Select Assessment Type" modal. Static UI strings, but
    # they were NOT here, so the 2026-08-10 capture came back as [redacted:19] and the
    # one thing the capture existed to learn was the one thing scrubbed out of it.
    #
    # Listing a label that turns out not to exist costs nothing: an allowlist entry
    # only ever permits an EXACT match, so a wrong name matches no text and reveals no
    # PHI. That asymmetry is why widening this list is safe while guessing a value to
    # TYPE into a form is not — the failure modes are opposites.
    "Physical Assessment", "PA Follow-Up", "PA Follow Up", "Physical Assessment Follow-Up",
    "HMA", "HMA's", "Health Management Assessment",
    "Office", "Office Visit", "Task", "Task Assessment",
    "Work Readiness", "Work Readiness Assessment",
    "Select Assessment Type", "Ergonomic Assessment", "Follow-Up", "Follow Up",
    # Generic table/UI words
    "of", "to", "and", "or", "Show", "Hide", "All", "None", "Required", "Optional",
]


_vocab = set()
_bootstrapped = False


def _norm(s):
    """Collapse whitespace + casefold, so 'Save  In Progress' == 'save in progress'."""
    return " ".join(str(s).split()).casefold()


def register_vocab(strings):
    """Add known-safe UI strings to the allowlist (idempotent)."""
    for s in strings or ():
        if s and str(s).strip():
            _vocab.add(_norm(s))


def _bootstrap():
    """Seed the vocabulary from static chrome + the EMR field-option lists."""
    global _bootstrapped
    if _bootstrapped:
        return
    register_vocab(UI_CHROME)
    try:
        with open(FIELD_OPTIONS_JSON, encoding="utf-8") as fh:
            for options in json.load(fh).values():
                register_vocab(options)
    except Exception:
        pass  # a missing options file just means a smaller allowlist — still safe
    _bootstrapped = True


# Text that is only punctuation/symbols carries no PHI — let it through so the
# markup stays readable. NOTE: digits are deliberately NOT safe (dates of birth,
# employee IDs, phone numbers, MRNs are all digits).
_PUNCT_ONLY = re.compile(r"^[^\w]*$", re.UNICODE)


def is_safe_text(text):
    """True only if `text` is a recognised EMR UI string (or pure punctuation)."""
    _bootstrap()
    if not text or not text.strip():
        return True
    if _PUNCT_ONLY.match(text):
        return True
    return _norm(text) in _vocab


def _placeholder(text):
    """Redact, but keep the length — enough to debug layout, useless to a reader."""
    return f"‹redacted:{len(text.strip())}›"


def redact_value(text):
    """Redact a single string unless it is known-safe vocabulary."""
    return text if is_safe_text(text) else _placeholder(text)


# ─────────────────────────────────────────────
# HTML SCRUBBING
# ─────────────────────────────────────────────

# Attributes whose values are structural (class names, ids, element types) and are
# what selector debugging actually needs. Kept verbatim.
STRUCTURAL_ATTRS = {
    "class", "id", "type", "role", "for", "tabindex", "style", "colspan",
    "rowspan", "disabled", "checked", "selected", "required", "readonly",
    "maxlength", "multiple", "hidden", "target", "rel", "width", "height",
    "name",  # form-field name: "description", "coaching_type" — never a person
}

# Content is dropped wholesale: it can embed bootstrapped state (JSON blobs of the
# roster), and it is never what you need to fix a selector.
DROP_CONTENT_TAGS = {"script", "style", "svg", "noscript", "template"}

# An <input type=checkbox|radio> value is an option code/UUID (the automation drives
# checkboxes by UUID), not typed text — safe to keep. A text/search/date input's
# value is whatever was typed into it, which is PHI.
_CODE_INPUT_TYPES = {"checkbox", "radio"}


class _Scrubber(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self._drop_depth = 0        # inside <script>/<style>/...
        self._drop_tag = None

    # -- tags -------------------------------------------------------------
    def _attrs_to_str(self, tag, attrs):
        adict = {k: (v or "") for k, v in attrs}
        parts = []
        for key, val in attrs:
            val = val or ""
            k = key.lower()
            if k in STRUCTURAL_ATTRS:
                keep = val
            elif k == "value":
                itype = adict.get("type", "").lower()
                # checkbox/radio codes are safe; typed-in values are not
                keep = val if (tag == "input" and itype in _CODE_INPUT_TYPES) \
                    else redact_value(val)
            elif k in ("href", "src"):
                # Keep the shape of the URL but kill any embedded identifiers.
                keep = re.sub(r"\d{2,}", "‹n›", val)
            else:
                # Unknown attribute (data-*, aria-label, title, alt, placeholder,
                # anything the EMR invents later): safe only if it is vocabulary.
                keep = redact_value(val)
            parts.append(f' {key}="{html_mod.escape(keep, quote=True)}"')
        return "".join(parts)

    def handle_starttag(self, tag, attrs):
        if self._drop_depth:
            if tag == self._drop_tag:
                self._drop_depth += 1
            return
        if tag in DROP_CONTENT_TAGS:
            self._drop_depth = 1
            self._drop_tag = tag
            self.out.append(f"<{tag}{self._attrs_to_str(tag, attrs)}>")
            return
        self.out.append(f"<{tag}{self._attrs_to_str(tag, attrs)}>")

    def handle_startendtag(self, tag, attrs):
        if self._drop_depth:
            return
        self.out.append(f"<{tag}{self._attrs_to_str(tag, attrs)}/>")

    def handle_endtag(self, tag):
        if self._drop_depth:
            if tag == self._drop_tag:
                self._drop_depth -= 1
                if self._drop_depth == 0:
                    self.out.append(f"</{tag}>")
                    self._drop_tag = None
            return
        self.out.append(f"</{tag}>")

    # -- content ----------------------------------------------------------
    def handle_data(self, data):
        if self._drop_depth:
            return  # contents of <script>/<style> never emitted
        if not data.strip():
            self.out.append(data)          # preserve indentation/newlines
            return
        if is_safe_text(data):
            self.out.append(html_mod.escape(data, quote=False))
        else:
            # keep surrounding whitespace so the markup stays readable
            lead = data[:len(data) - len(data.lstrip())]
            trail = data[len(data.rstrip()):]
            self.out.append(f"{lead}{_placeholder(data)}{trail}")

    def handle_comment(self, data):
        pass  # comments can carry server-side state; never worth keeping

    def handle_decl(self, decl):
        self.out.append(f"<!{decl}>")

    def result(self):
        return "".join(self.out)


def scrub_html(html):
    """Return `html` with every non-vocabulary string replaced by a placeholder.

    Structure (tags, ids, classes, form-field names, checkbox codes) is preserved —
    that is what selector debugging needs. Text, typed values, URLs' identifiers,
    comments and <script>/<style> bodies are removed.

    Fails closed: if parsing blows up, returns a stub rather than raw HTML.
    """
    try:
        s = _Scrubber()
        s.feed(html)
        s.close()
        return s.result()
    except Exception as e:
        return f"<!-- phi_redact: scrub failed ({type(e).__name__}); HTML withheld -->"


# ─────────────────────────────────────────────
# SCREENSHOTS
# ─────────────────────────────────────────────

# Regions painted over before a screenshot is written. Unlike scrub_html(), this is
# a denylist — a screenshot is pixels, and we cannot prove an unlisted region is
# clean. That is why screenshots are OFF by default (see DEBUG_SCREENSHOTS).
MASK_SELECTORS = [
    ".employee-list",      # the entire preloaded roster
    ".employee-details",
    ".patient-banner",
    "input",               # anything typed (names, DOB, identifiers)
    "textarea",            # the clinical free-text description
    "table",               # case/encounter history rows
]


def screenshot_masks(page):
    """Locators to hand to Playwright's screenshot(mask=...)."""
    return [page.locator(sel) for sel in MASK_SELECTORS]


# ─────────────────────────────────────────────
# CONSOLE
# ─────────────────────────────────────────────

_aliases = {}


def console_redaction_on():
    """Redact names/free-text on stdout?

    Default: ON whenever stdout is NOT a terminal.

    That is the important bit. When Dane runs this in a console window, stdout is a
    tty and he sees real names — which he needs. When anything *captures* stdout
    instead — an AI assistant running the script as a subprocess, a piped log file,
    a CI job — it is not a tty, and redaction switches on by itself. Nobody has to
    remember a flag, and the failure mode of forgetting one is "no leak" rather than
    "leak".

    Override either way with EMR_REDACT_CONSOLE=1 / =0.
    """
    flag = os.environ.get(ENV_FLAG, "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    try:
        return not sys.stdout.isatty()
    except Exception:
        return True  # can't tell → assume captured → redact


def alias(value):
    """Stable per-run pseudonym: 'Smith, Jane' → 'Employee #1'.

    The mapping lives in memory only; it is never written to disk, so a transcript
    of a redacted run cannot be reversed back into names.
    """
    key = _norm(value)
    if key not in _aliases:
        _aliases[key] = f"Employee #{len(_aliases) + 1}"
    return _aliases[key]


def ph(value):
    """Print-helper for a NAME. Real name normally; alias when redaction is on."""
    if not value:
        return value
    return alias(value) if console_redaction_on() else value


def pv(value):
    """Print-helper for a FIELD VALUE (phone, date of birth, identifier, address).

    Unlike ph(), there is no stable alias — these are attributes, not people, so
    aliasing them would be noise. Known-safe vocabulary (a department, a shift, a
    division) passes through, which keeps roster-update logs readable: you still
    see 'set Department: Weld -> Assembly', but 'set Phone: [redacted:10]'.
    """
    if value is None or value == "":
        return value
    if not console_redaction_on():
        return value
    text = str(value)
    if is_safe_text(text):
        return text
    return f"[redacted:{len(text.strip())}]"


def pd(value):
    """Print-helper for FREE TEXT (the clinical description).

    ASCII-only on purpose: this goes to stdout, and a redacted run is exactly the
    case where stdout is piped (to a log, to an assistant) rather than sent to a
    UTF-8 console — so no fancy quote characters that could blow up on cp1252.
    """
    if not value:
        return value
    if not console_redaction_on():
        return value
    return f"[description redacted: {len(str(value).strip())} chars]"
