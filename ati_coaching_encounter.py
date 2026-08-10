"""
ATI Worksite Solutions - Coaching Encounter Automation
======================================================
Automates entry of Coaching Encounters into the ATI EMR system.

SETUP:
    pip install playwright
    playwright install chromium

USAGE:
    1. Run: python ati_coaching_encounter.py
    2. Answer the on-screen questions for this one encounter (employee, date,
       coaching type, details, etc.). Press ENTER to accept a default.
    3. The script opens a browser, you log in, then it finds the employee and
       fills the form for you.
    4. It pauses before final Save so you can review before submitting.

    Run it again for the next encounter.

SEMI-AUTO MODE (recommended):
    Set AUTO_SUBMIT = False to pause at the Save button for manual review.
"""

import asyncio
import csv
import ctypes
import json
import os
import re
import sys
from playwright.async_api import async_playwright, Page
from datetime import date, datetime

import emr_field_map
import name_match
import phi_redact
from phi_redact import ph, pd  # ph(name) / pd(free text) — see PHI NOTE below

# ─────────────────────────────────────────────
# CONFIG — fill these in before running
# ─────────────────────────────────────────────

# How each encounter is committed:
#   "draft"  — click "Save in progress": saves a DRAFT you review/finalize later in
#              the EMR's InProgress list. Never finalizes. Best for unattended
#              batches. (default)
#   "review" — fill the form, then pause so you can review and choose save/skip/quit.
#   "final"  — click the real Save automatically (finalizes the encounter). Careful.
SAVE_MODE = "draft"

# Set to True (during testing) to save page HTML at each step into a ./debug folder.
# These captures let us fix selectors against the real EMR.
#
# PHI NOTE: captured HTML is run through phi_redact.scrub_html() before it is
# written. Only known EMR UI strings survive; everything else — names, dates of
# birth, identifiers, the free-text description — is replaced with a placeholder.
# The debug folder is therefore safe to share (with an AI assistant, in a bug
# report). See phi_redact.py for why this is an allowlist and not a denylist.
DEBUG_CAPTURE = True

# Screenshots are a separate, stricter switch. Redacting a PNG means painting over
# regions we remembered to list (phi_redact.MASK_SELECTORS) — a denylist, so an
# unlisted corner of the page could still show a name. HTML is what selector
# debugging actually needs, so screenshots stay OFF unless you deliberately want
# them. When on, the known PHI regions are masked, but treat the PNGs as sensitive.
DEBUG_SCREENSHOTS = False

BASE_URL = "https://aws.atiworksitesolutions.com"

# Persistent browser profile folder. Stores cookies + cache so the browser
# remembers your login AND your selected worksite (org) between runs — just like
# your normal Edge/Chrome does. Created automatically on first run.
USER_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".browser_profile")

# Batch input file. If this CSV exists next to the script, you'll be offered batch
# mode: it reads each row, fills the form, and pauses for your review per encounter.
# An AI (Claude/ChatGPT) transcribes your dictated notes into this file — see
# encounter_builder.py, which can only emit values the EMR accepts.
ENCOUNTERS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "encounters.csv")
# Same backup file encounter_builder writes before it replaces a batch.
ENCOUNTERS_BAK_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "encounters.bak.csv")

# Per-run audit log. Every encounter's outcome (saved / skipped / error / name not
# matched) is appended here as it happens, so a run is reviewable AFTER the fact — the
# gap that left 14 errors reconstructable only from redacted screenshots. It holds real
# names, so it's PHI: gitignored, and reviewed via `--audit` (which redacts for anyone
# but Dane). One file, appended across runs; the run_started column separates them.
ENCOUNTER_LOG_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "encounter_log.csv")
ENCOUNTER_LOG_COLUMNS = ["run_started", "logged_at", "row", "employee", "matched_to",
                         "coaching_type", "date", "status", "note"]


def log_encounter(run_started, row_no, employee, matched_to, coaching_type,
                  enc_date, status, note=""):
    """Append one outcome to the audit log. Never raises — logging must not break a run."""
    try:
        new_file = not os.path.exists(ENCOUNTER_LOG_CSV)
        with open(ENCOUNTER_LOG_CSV, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=ENCOUNTER_LOG_COLUMNS)
            if new_file:
                w.writeheader()
            w.writerow({
                "run_started": run_started,
                "logged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "row": row_no,
                "employee": employee or "",
                "matched_to": matched_to or "",
                "coaching_type": coaching_type or "",
                "date": enc_date or "",
                "status": status,
                "note": note or "",
            })
    except Exception as e:
        print(f"  [audit] could not write log row: {e}")

# The Department / Division / Category / Shift dropdown vocabularies, captured from the
# live EMR form. These are validated up front so a bad value fails at the desk, with a
# list of what's allowed — rather than silently mid-run, when react_select goes looking
# for an option that was never there.
FIELD_OPTIONS_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "emr_field_options.json")


def _load_field_options():
    try:
        with open(FIELD_OPTIONS_JSON, encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return {}  # no options file → skip these checks rather than block the run
    # "Select" is the EMR's own empty-choice placeholder, not a real value.
    return {field: [v for v in values if v and v != "Select"]
            for field, values in raw.items()}


FIELD_OPTIONS = _load_field_options()

# CSV column -> the EMR field whose option list governs it.
DROPDOWN_COLUMNS = {
    "department": "Department",
    "division": "Division",
    "category": "Category",
    "shift": "Shift",
}

# ─────────────────────────────────────────────
# MENU OPTIONS — used by the on-screen questions
# ─────────────────────────────────────────────

ENCOUNTER_TYPES = [
    "In Person",
    "Via Phone or Microsoft Teams",
    "Via Telehealth Platform",
    "Via Email",
]

# First entry is the default (used when a CSV row or prompt leaves it blank).
# Dane usually initiates the conversation, so Specialist Initiated leads.
WHAT_PROMPTED_OPTIONS = [
    "Specialist Initiated",
    "Employee Inquiry",
    "Demonstrated risk factor at job site",
    "Employer prompted contact",
]

# ─────────────────────────────────────────────
# COACHING TYPE → UUID MAP
# (captured from the live form HTML)
# ─────────────────────────────────────────────

COACHING_TYPE_UUIDS = {
    "Safety Coaching":                               "c69dcbe8-6154-4c15-9ce7-e489a969da95",
    "Relationship Development Encounter":            "f714091a-0535-4414-847a-a0ba01d7c7cf",
    "Near Miss Education":                           "343366b2-17b3-4778-bcde-96352cabbd57",
    "Group Class":                                   "908e5669-ae84-4e0c-b7fa-7605d2383492",
    "Job-Specific Preventative Mobility/Stretching": "ed0ce7a7-349a-41ac-8c6b-8f62da8e5de8",
    "Job-Specific Coaching":                         "678fcc62-1b17-40e0-ad12-237d6c74f8ae",
    "Health/Wellness Coaching":                      "33e07b20-5b38-4e6b-8618-c7178fa3c187",
    "General Medical Education":                     "69ff2e61-f96b-48af-9742-12140a61d07f",
    "Friend/Family Consultation":                    "5460c453-b1e8-42a9-97a0-34829dd01976",
    "Fitness Center Visit":                          "bfe14e28-b996-47b5-a0be-ebb510d01cbb",
    "Ergonomic Adjustment":                          "331e50be-893d-48de-b465-b053175ec9d5",
}

# ─────────────────────────────────────────────
# CHECKBOX UUID MAPS PER COACHING TYPE
# ─────────────────────────────────────────────

HEALTH_WELLNESS_CHECKBOX_UUIDS = {
    "Hydration":                 "f7be5275-faed-4919-9ac6-f9623c85007a",
    "Nutrition":                 "2a298545-d3d9-4b19-9d50-aa3e693e9d32",
    "Other":                     "002b7c1f-bd6c-413a-a0cc-80598262cd5c",
    "Personal exercise/fitness": "7b3fbbbd-ebe9-4025-91df-b2c36d1f7fb0",
    "Sleep":                     "88e62660-bc0d-4d16-8696-c5104f2ddff8",
    "Stress":                    "eb3835c9-f284-4d05-92c0-34ee2802e5c2",
}

ERGONOMIC_ADJUSTMENT_CHECKBOX_UUIDS = {
    "Industrial ergo adjustment": "5760eaf5-7718-4b52-a0ee-85195e5144b6",
    "Office ergo adjustment":     "ae7e9755-dfea-43b5-bf7c-59deacb2c570",
    "Other":                      "8eabf743-161b-4b5a-aef6-cbed7bc90068",
    "Tools adjustment":           "1a1caf56-db62-4d3a-bb83-dc8c924fa3b4",
}

FITNESS_CENTER_CHECKBOX_UUIDS = {
    "Focus: Class":             "f0563ed5-3d7a-4768-9db3-d6ae71bead95",
    "Focus: Endurance":         "cf21a8af-636b-4719-af64-81b7a8b2d97f",
    "Focus: Flexibility":       "b86e1c66-0ac5-46fe-a466-3379483791a5",
    "Focus: Recreational Event":"5ab07458-c00c-48c8-82f0-bb121f41e1e2",
    "Focus: Strength":          "e10ba57a-4724-4f47-be8b-adff8d7bbe14",
    "Orientation":              "f3c2849a-0d91-432f-9394-6365326355a0",
}

GENERAL_MEDICAL_CHECKBOX_UUIDS = {
    "Blood Pressure/Pulse Check":  "32c944ee-ca1a-4d6a-999b-5f3ee96a7a29",
    "Cold modality instruction":   "429257b7-791e-4d15-ae66-19abd84266c8",
    "Extreme heat/cold education": "c452bac9-d9f6-4c0a-bc8a-78fa984f784f",
    "OTC medications":             "35f3f3a0-499d-4bf0-867c-9985f7f0ec3b",
    "Other":                       "b2d7bd88-58c1-4cb9-9026-fb051d95485a",
    "Psychosocial":                "c7b6d544-31da-4d98-a8b7-a4e438f48e4a",
    "Self-care":                   "232d00d0-bcf0-47bd-9197-e12d06074ff4",
    "Thermal modality instruction":"ffcd873b-6031-4be1-a92f-54575fd55492",
    "Wound care instruction":      "c149d84d-d331-457f-983f-e34eb420035d",
}

# Friend/Family Consultation and Job-Specific Preventative Mobility/Stretching
# have no checkboxes — description + prompted only

JOB_SPECIFIC_COACHING_CHECKBOX_UUIDS = {
    "Body Mechanics":           "f9d1ef8e-e97f-4332-b134-ab2263716697",
    "Material handling":        "9a0136da-dd0b-4b3c-846a-9ea1f77bf15f",
    "Other job coaching":       "9a8c4a9c-3ae1-4d01-be94-7fe9a16de2b7",
    "Postural/Position Coaching":"b9775fde-ab20-4f70-bc03-6785b8186807",
    "Proper lifting":           "0896afac-6dcb-411f-b8f8-6e66ee89fc4d",
    "Proper loading/unloading": "769adff5-d9f5-4e68-9f7b-c2efb173a212",
    "Proper push/pull":         "69e9e3d1-355e-44e4-a91e-4ae31b727438",
    "Rest break":               "35e157a2-4066-40c4-a558-dd1b59ea7294",
    "Rest (task design)":       "d82eb71b-0488-4957-8f21-703da6075795",
    "Tool/equipment handling":  "5aefbc33-97e2-48be-9387-de43277b7d46",
}

GROUP_CLASS_CHECKBOX_UUIDS = {
    "New Hire Orientation":                    "8f2f9dd1-bc6e-4c03-8339-490fac2d4bc3",
    "Other":                                   "306137e8-c33f-439f-bcc5-b65e67bf6e3e",
    "Safety Meeting":                          "1fffb234-3ecc-4f61-9bc8-3a28369d06a9",
    "Pre-shift Meeting":                       "380c8d6e-d842-493f-9215-552bbf33e292",
    "Group Preventative Mobility":             "aea0899b-1d0f-4cd4-87a9-442c575e230c",
    "Annual Testing":                          "6304b690-0c0f-4767-9097-94b092f9573b",
    "Department Weekly/Monthly Safety Meetings":"00b3dc1e-e7f3-434a-ae56-2dfee6edb71d",
    "First Aid Team Meeting":                  "cf051651-ba39-4588-a2cc-b01ea28410b8",
    "Management Meetings":                     "e27599c2-cc16-4f07-b703-10eb734a967a",
    "Safety Fair":                             "4dd064fa-b1c7-4a56-b047-b66078584e34",
}

SAFETY_COACHING_CHECKBOX_UUIDS = {
    "3-point contact":         "217871ef-ba8e-49d0-9e1c-ee3ca564fd67",
    "Awareness/alertness":     "889ab116-fabd-41c7-a4e2-41dbf441bb5e",
    "Other":                   "319a6a04-b2d0-41f0-ad2c-b85b135d4756",
    "PPE Use":                 "ba05e7dc-8bd0-47ad-a843-62267bfd3433",
    "Safety Hazard":           "c6919f3a-62ff-4c55-827b-97d45a6b655b",
    "Slip/trip/fall Prevention":"f4befbfc-cac9-4ced-a599-24045c7a35f5",
    "Unsafe Behavior":         "8fe767ec-1b19-48ff-a23b-bc9ed0c03b6c",
}

RELATIONSHIP_DEVELOPMENT_CHECKBOX_UUIDS = {
    "Current Employee": "7f0abbbb-9694-424c-83ce-f84657e5eb28",
    "New Hire":         "e8f1da33-547b-49f4-9913-6e8a04f0131b",
}

# Master lookup — maps coaching type name to its checkbox UUID dict
CHECKBOX_UUID_MAP = {
    "Health/Wellness Coaching":                      HEALTH_WELLNESS_CHECKBOX_UUIDS,
    "Ergonomic Adjustment":                          ERGONOMIC_ADJUSTMENT_CHECKBOX_UUIDS,
    "Fitness Center Visit":                          FITNESS_CENTER_CHECKBOX_UUIDS,
    "General Medical Education":                     GENERAL_MEDICAL_CHECKBOX_UUIDS,
    "Job-Specific Coaching":                         JOB_SPECIFIC_COACHING_CHECKBOX_UUIDS,
    "Group Class":                                   GROUP_CLASS_CHECKBOX_UUIDS,
    "Safety Coaching":                               SAFETY_COACHING_CHECKBOX_UUIDS,
    "Relationship Development Encounter":            RELATIONSHIP_DEVELOPMENT_CHECKBOX_UUIDS,
    "Friend/Family Consultation":                    {},  # no checkboxes
    "Job-Specific Preventative Mobility/Stretching": {},  # no checkboxes
    "Near Miss Education":                           {},  # no checkboxes
}

# ── PHI redaction vocabulary ──────────────────
# Teach the scrubber every string the EMR form is *allowed* to show. Anything not
# registered here (or in phi_redact's own chrome/field-option lists) is redacted out
# of debug captures — which is precisely what keeps employee names from surviving.
# If a debug capture hides a label you needed, register it here rather than
# loosening the scrubber.
phi_redact.register_vocab(ENCOUNTER_TYPES)
phi_redact.register_vocab(WHAT_PROMPTED_OPTIONS)
phi_redact.register_vocab(COACHING_TYPE_UUIDS)          # coaching type names
for _group in CHECKBOX_UUID_MAP.values():
    phi_redact.register_vocab(_group)                   # detail-checkbox labels
# The new "In Progress" navigation prompt (EMR chrome, not PHI) — register so a debug
# capture of it stays readable for selector work.
phi_redact.register_vocab([
    "There are active encounters that have been saved 'In Progress'.",
    "Would you like to navigate to the 'In Progress' case list?",
    "In Progress", "Yes", "No",
])

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def name_pattern(full_name):
    """Build a whitespace-tolerant regex for a 'Last, First' name so it still matches
    the EMR's inconsistent formatting — e.g. 'Doe , Jane' (space before the comma),
    'Poe, William "Will"' (trailing nickname), or 'Van Dam, Kay' (two-word
    last name). Spaces become \\s+ and the comma tolerates surrounding whitespace.
    """
    parts = [p.strip() for p in str(full_name).split(",") if p.strip()]
    tokens = [r"\s+".join(re.escape(w) for w in p.split()) for p in parts]
    return re.compile(r"\s*,\s*".join(tokens), re.IGNORECASE)


class AlreadyInProgress(Exception):
    """The employee already has an In Progress case, so the EMR won't let us add one.

    Not an error in the batch's sense: it's this employee's state in the EMR, it says
    nothing about the CSV or the automation, and it will keep happening until Dane
    closes the existing draft. Kept separate so it doesn't trip the circuit breaker
    and doesn't hide in the audit behind a generic timeout.
    """


async def snap(page: Page, label: str):
    """Save the page's (PHI-redacted) HTML to ./debug for selector debugging.

    The HTML is scrubbed before it touches the disk — raw page content is never
    written. Screenshots are only taken if DEBUG_SCREENSHOTS is on, and then with
    the known PHI regions masked out.

    No-op unless DEBUG_CAPTURE is True. Never raises — a capture failure should
    not interrupt the run.
    """
    if not DEBUG_CAPTURE:
        return
    try:
        folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug")
        os.makedirs(folder, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        base = os.path.join(folder, f"{ts}_{label}")

        # Scrub BEFORE writing: the raw HTML only ever exists in memory.
        safe_html = phi_redact.scrub_html(await page.content())
        with open(base + ".html", "w", encoding="utf-8") as fh:
            fh.write(safe_html)

        if DEBUG_SCREENSHOTS:
            await page.screenshot(path=base + ".png", full_page=True,
                                  mask=phi_redact.screenshot_masks(page))

        print(f"  [debug] captured: {label}")
    except Exception as e:
        print(f"  [debug] capture failed for '{label}': {e}")


async def react_select(page: Page, label: str, option_text: str, required: bool = True):
    """Open the ati-react-select dropdown under a given field LABEL and pick an option.

    Targets the control by its label text (e.g. "Department", "Coaching Type")
    rather than the auto-generated react-select id, which changes between renders.
    If `required` is False, a failure is logged and skipped instead of raising.
    """
    try:
        control = page.locator(
            f"xpath=//label[normalize-space(.)='{label}']/following-sibling::div[1]"
            f"//div[contains(@class,'ati-react-select__control')]"
        ).first
        await control.click(timeout=6000)
        await page.wait_for_timeout(400)
        option = page.locator(".ati-react-select__option", has_text=option_text).first
        await option.click(timeout=6000)
        await page.wait_for_timeout(300)
    except Exception as e:
        print(f"  WARNING: couldn't set '{label}' = '{option_text}': "
              f"{str(e).splitlines()[0]}")
        await page.keyboard.press("Escape")  # close any open menu
        if required:
            raise


async def fill_date(page: Page, value: str):
    """Set the Date of Encounter via the rc-calendar popup, then click Apply.

    The picker ignores a typed value, so we open the calendar, navigate to the
    target month, click the day cell (matched by its `title`, e.g.
    "June 23, 2026"), and confirm with Apply.
    """
    target = datetime.strptime(value, "%m/%d/%Y")
    title = f"{target.strftime('%B')} {target.day}, {target.year}"  # "June 23, 2026"

    date_input = page.locator("input.form-field-input[placeholder='Date of Encounter']")
    await date_input.click()
    await page.wait_for_timeout(400)  # calendar opens on the current month

    # Navigate months relative to today's month (the calendar's default view).
    today = date.today()
    delta = (target.year - today.year) * 12 + (target.month - today.month)
    if delta != 0:
        cls = "rc-calendar-next-month-btn" if delta > 0 else "rc-calendar-prev-month-btn"
        btn = page.locator(f".{cls}")
        for _ in range(abs(delta)):
            await btn.click()
            await page.wait_for_timeout(150)

    await page.locator(f"td[role='gridcell'][title='{title}']").click(timeout=6000)
    await page.wait_for_timeout(200)

    apply_btn = page.get_by_role("button", name="Apply", exact=True)
    if await apply_btn.count() > 0:
        await apply_btn.click()
    await page.wait_for_timeout(300)


async def click_radio(page: Page, value: str):
    """Select an encounter-type tile. The radio <input> is hidden, so click its
    label (the visible tile), which is wrapped in `label.segment-select[for=VALUE]`."""
    await page.locator(f"label.segment-select[for='{value}']").click()
    await page.wait_for_timeout(200)


async def tick_checkbox(page: Page, uuid: str):
    """Check a coaching detail checkbox by its UUID (best-effort).

    The <input> is visually hidden inside a `<label class="custom-checkbox">`, so
    we click the wrapping label to toggle it (the same pattern as the radio tiles).
    """
    try:
        checkbox = page.locator(f"input[name='coachingDetailTypes'][value='{uuid}']")
        if not await checkbox.is_checked(timeout=6000):
            label = checkbox.locator(
                "xpath=ancestor::label[contains(@class,'custom-checkbox')][1]"
            )
            await label.click(timeout=6000)
        await page.wait_for_timeout(150)
    except Exception as e:
        print(f"  WARNING: couldn't tick detail checkbox: {str(e).splitlines()[0]}")


# ─────────────────────────────────────────────
# INTERACTIVE PROMPTS (one encounter per run)
# ─────────────────────────────────────────────

def popup(message, title="EMR AutoMate", yes_no=False):
    """Show a native Windows dialog ON TOP of the browser so you don't have to
    switch back to PowerShell. Returns True for OK/Yes, False for Cancel/No.

    Falls back to a terminal prompt if no GUI is available.
    """
    try:
        MB_OKCANCEL = 0x00000001
        MB_YESNO = 0x00000004
        MB_ICONQUESTION = 0x00000020
        MB_SETFOREGROUND = 0x00010000
        MB_TOPMOST = 0x00040000
        style = ((MB_YESNO if yes_no else MB_OKCANCEL)
                 | MB_ICONQUESTION | MB_SETFOREGROUND | MB_TOPMOST)
        result = ctypes.windll.user32.MessageBoxW(0, message, title, style)
        return result in (1, 6)  # IDOK = 1, IDYES = 6
    except Exception:
        hint = "Y/n" if yes_no else "Enter = OK, or type n to cancel"
        ans = input(f"{message}  [{hint}]: ").strip().lower()
        return ans not in ("n", "no")


def ask_text(label, default=None, required=False):
    """Ask for free text. ENTER accepts the default (or skips if optional)."""
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"{label}{suffix}: ").strip()
        if not val and default is not None:
            return default
        if not val and not required:
            return ""
        if val:
            return val
        print("  This field is required.")


def ask_choice(label, options, default=0):
    """Show a numbered menu and return the chosen option text."""
    print(label)
    for i, opt in enumerate(options, 1):
        marker = "  (default)" if i - 1 == default else ""
        print(f"  {i}) {opt}{marker}")
    while True:
        raw = input(f"Choose [1-{len(options)}] [{default + 1}]: ").strip()
        if not raw:
            return options[default]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print("  Enter a number from the list.")


def ask_multi(label, options):
    """Show a numbered menu and return a list of chosen option texts."""
    if not options:
        return []
    print(f"{label} (comma-separated numbers, or ENTER for none):")
    for i, opt in enumerate(options, 1):
        print(f"  {i}) {opt}")
    while True:
        raw = input("Select: ").strip()
        if not raw:
            return []
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if all(p.isdigit() and 1 <= int(p) <= len(options) for p in parts):
            return [options[int(p) - 1] for p in parts]
        print("  Enter numbers from the list, separated by commas.")


def prompt_encounter():
    """Collect one encounter's data from the user and return it as a dict."""
    print("\n══════════════════════════════════════════")
    print("  New Coaching Encounter")
    print("══════════════════════════════════════════\n")

    employee = ask_text("Employee name (Last, First)", required=True)
    date_of_encounter = ask_text("Date of encounter",
                                 default=date.today().strftime("%m/%d/%Y"))
    print()
    encounter_type = ask_choice("Encounter type:", ENCOUNTER_TYPES, default=0)

    print("\nOptional details — press ENTER to skip any of these.")
    department = ask_text("Department") or None
    division = ask_text("Division") or None
    category = ask_text("Category") or None
    shift = ask_text("Shift") or None

    print()
    coaching_types = list(COACHING_TYPE_UUIDS.keys())
    default_idx = coaching_types.index("Health/Wellness Coaching")
    coaching_type = ask_choice("Coaching type:", coaching_types, default=default_idx)

    detail_options = list(CHECKBOX_UUID_MAP.get(coaching_type, {}).keys())
    print()
    coaching_detail_types = ask_multi(f"{coaching_type} details", detail_options)

    print()
    description = ask_text("Description (optional)")
    print()
    what_prompted = ask_choice("What prompted the coaching?",
                               WHAT_PROMPTED_OPTIONS, default=0)

    encounter = {
        "employee_search": employee,
        "date_of_encounter": date_of_encounter,
        "encounter_type": encounter_type,
        "department": department,
        "division": division,
        "category": category,
        "shift": shift,
        "coaching_type": coaching_type,
        "coaching_detail_types": coaching_detail_types,
        "description": description,
        "what_prompted": what_prompted,
    }

    # ── Review summary ─────────────────────────
    print("\n──────────────────────────────────────────")
    print("  Review")
    print("──────────────────────────────────────────")
    print(f"  Employee:       {ph(employee)}")
    print(f"  Date:           {date_of_encounter}")
    print(f"  Encounter type: {encounter_type}")
    if department:
        print(f"  Department:     {department}")
    if division:
        print(f"  Division:       {division}")
    if category:
        print(f"  Category:       {category}")
    if shift:
        print(f"  Shift:          {shift}")
    print(f"  Coaching type:  {coaching_type}")
    details = ", ".join(coaching_detail_types) if coaching_detail_types else "(none)"
    print(f"  Details:        {details}")
    if description:
        print(f"  Description:    {pd(description)}")
    print(f"  Prompted by:    {what_prompted}")
    print("──────────────────────────────────────────")

    again = input("\nLook right? ENTER to launch, or type 'r' to re-enter: ").strip().lower()
    if again == "r":
        return prompt_encounter()
    return encounter


# ─────────────────────────────────────────────
# MAIN FLOW
# ─────────────────────────────────────────────

# The employee's display name, and nothing else. Each dashboard row is
#   <div id="UUID" class="details..."> ... <span class="name">Last, First</span>
#                                          <span class="badge-id"># 12345 - Title</span>
# (the same structure update_employees._ROW_RE parses, verified against a saved
# 938-row dashboard capture and used by the roster-update runs).
_NAME_SEL = ".employee-list .details .name"


async def roster_names(page: Page):
    """Every employee display name currently in the dashboard's .employee-list.

    READ THE .name SPANS — never the row's rendered text.
        An earlier version took each row's inner_text and assumed the display name was
        its first line. But the name and badge are adjacent inline <span>s: how that
        text wraps into "lines" is a CSS accident, and when it doesn't wrap the way the
        code hoped, every candidate becomes junk like 'Doe, John# 12345 - Welder' and
        every real name in the batch comes back "not found" — 77 of 77, names that
        were sitting right there on the screen. The .name span is the EMR's own
        definition of the display name; use it.

    WAIT FOR THE LIST FIRST — also load-bearing.
        all_inner_texts() does NOT auto-wait: it returns whatever is in the DOM at
        that instant. The roster is React-rendered and lands AFTER `networkidle`, so
        reading straight after page.goto() can return an empty list — downstream,
        indistinguishable from "none of these people exist". Wait for rows to appear,
        then for the count to stop growing.
    """
    try:
        await page.wait_for_selector(_NAME_SEL, state="attached", timeout=30000)
    except Exception:
        return []          # caller decides what an empty roster means

    # The list streams in; settle before reading, or we read a partial roster and
    # "not found" a person who was simply still on their way.
    previous, stable = -1, 0
    for _ in range(40):
        current = await page.locator(_NAME_SEL).count()
        if current and current == previous:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        previous = current
        await page.wait_for_timeout(250)

    return [t.strip() for t in await page.locator(_NAME_SEL).all_inner_texts()]


async def locate_employee(page: Page, full_name):
    """Find one employee's row, tolerating nicknames. Raises if absent or ambiguous.

    Dane dictates the name he uses out loud — "Thompson, Bill" — and the EMR holds the
    formal one, "Thompson, William". The old strict regex only ever worked when the
    nickname happened to be a PREFIX of the formal name ("Will"), which is why "Bill",
    "Bob" and "Peggy" failed. name_match handles the rest.

    Ambiguity is never resolved by guessing: if "Smith, Chris" could be Christopher or
    Christina, this raises. Attaching an encounter to the wrong person's medical record
    is a far worse outcome than stopping to ask.
    """
    # Fast path: the strict pattern, which already tolerates the EMR's spacing and
    # trailing quoted nicknames.
    pattern = name_pattern(full_name)
    rows = page.locator(".employee-list .details", has_text=pattern)
    if await rows.count() == 1:
        await snap(page, "02_employee_list")
        return rows.first

    # Narrow the (long) list by surname first — the search box is a client-side filter.
    last_name = full_name.split(",")[0].strip()
    if last_name:
        box = page.locator("input[placeholder='Search Employee or Identifier']")
        await box.click()
        await box.fill(last_name)
        await page.wait_for_timeout(1200)

    await snap(page, "02_employee_list")

    candidates = await roster_names(page)

    # An empty list is a RENDER failure, not a bad name — the same distinction
    # preflight_names already makes ("roster-empty", not 77 bad names), which this
    # function was missing. Verified on the 2026-07-29 run: the two rows that failed
    # here had 0 `.name` spans in their 02 capture (a 19,770-byte skeleton of 10
    # placeholder `.details` rows) where a healthy capture in the same run had 938.
    # roster_names() waits 30s for a `.name` to attach and then returns [], which
    # find_matches turns into "couldn't find employee" — sending Dane to fix a name
    # the pre-flight had already matched against the full roster. Reload and match
    # against the UNFILTERED roster (the search box is only a speed-up, and it is
    # what emptied the list); say "the page didn't load" only if that fails too.
    if not candidates:
        print("  Employee list came back empty — reloading and retrying once...")
        await page.goto(BASE_URL)
        await page.wait_for_load_state("networkidle")
        await dismiss_in_progress_prompt(page)
        candidates = await roster_names(page)
        await snap(page, "02b_employee_list_retry")
        if not candidates:
            raise RuntimeError(
                "The employee list didn't load — 0 names on the page, after a reload. "
                "That's a page/render failure, NOT a name problem: encounters.csv is "
                "fine, leave it alone. Re-run with --resume once the EMR responds."
            )

    idx, how = name_match.find_matches(full_name, candidates)

    if len(idx) == 1:
        formal = candidates[idx[0]]
        if how != "exact":
            print(f"  Matched {ph(full_name)} -> {ph(formal)}  ({how})")
        # Select the row CONTAINING that exact name span. An index into the names
        # list only maps back to the right row if every row has exactly one name
        # span — content can't misalign. (find_matches already raised on duplicates,
        # so an exact-text filter is unambiguous here.)
        row = page.locator(".employee-list .details").filter(
            has=page.locator(".name", has_text=re.compile(
                rf"^\s*{re.escape(formal)}\s*$")))
        if await row.count() >= 1:
            return row.first
        return page.locator(".employee-list .details").nth(idx[0])

    if len(idx) > 1:
        options = " | ".join(ph(candidates[i]) for i in idx)
        raise RuntimeError(
            f"'{ph(full_name)}' is ambiguous — it matches {len(idx)} employees: "
            f"{options}. Use the full formal name in encounters.csv so there's no doubt."
        )

    raise RuntimeError(
        f"Couldn't find employee '{ph(full_name)}'. Check the spelling and the "
        f"'Last, First' format, and that they're in this worksite."
    )


async def preflight_names(page: Page, encounters):
    """Resolve every name in the batch BEFORE entering anything.

    Without this, a bad name is only discovered when its turn comes — halfway through
    an 80-encounter run, with a dialog to click for each one. Better to find out at the
    start, while the CSV is still easy to fix.

    Returns (matched, problems). Does not modify anything.
    """
    await page.goto(BASE_URL)
    await page.wait_for_load_state("networkidle")
    candidates = await roster_names(page)

    # An empty roster is a LOAD failure, not 77 bad names. Reporting it as unmatched
    # names sends Dane to fix a CSV that was never wrong. Distinguish the two: no
    # candidates at all means the dashboard didn't render (or the worksite isn't
    # selected), so say that and enter nothing.
    if not candidates:
        return {}, "roster-empty"

    # Count only — PHI-safe — and exactly the number you need when a batch reports
    # unmatched names: it says whether the comparison list was sane.
    print(f"  Roster loaded: {len(candidates)} employee(s) on the dashboard.")

    matched, problems, seen = {}, [], set()
    for enc in encounters:
        nm = (enc.get("employee_search") or "").strip()
        if not nm or nm in seen:
            continue
        seen.add(nm)
        idx, how = name_match.find_matches(nm, candidates)
        if len(idx) == 1:
            matched[nm] = (candidates[idx[0]], how)
        elif len(idx) > 1:
            problems.append((nm, "ambiguous", [candidates[i] for i in idx]))
        else:
            problems.append((nm, "not found", []))
    return matched, problems


async def _looks_logged_out(page: Page) -> bool:
    """Is the page showing the login screen? (Same probe update_employees uses.)"""
    try:
        if await page.get_by_text("Login to your account").count() > 0:
            return True
        if await page.get_by_role("button", name="Login", exact=True).count() > 0:
            return True
    except Exception:
        pass
    return False


# The EMR tech team added a modal (seen 2026-07-23) that pops on the dashboard whenever
# there are drafts, and blocks the next save until it's answered: "There are active
# encounters that have been saved 'In Progress'. Would you like to navigate to the 'In
# Progress' case list?" with Yes / No. Since the batch is mid-draft, there are ALWAYS
# in-progress cases after row 1, so it fires every row. We answer NO — stay put and keep
# drafting; Yes would navigate away and derail the batch.
_INPROGRESS_PROMPT_RE = re.compile(r"navigate to the|active encounters", re.I)


async def dismiss_in_progress_prompt(page: Page) -> bool:
    """Click 'No' on the EMR's 'navigate to the In Progress case list?' modal if it's up.

    Detected on the LIVE DOM (so redaction of debug HTML doesn't affect it) and entirely
    non-fatal: returns quickly when the modal isn't there, never raises. Snaps the modal
    (scrubbed) the first time it's seen so the real markup is on record if the click ever
    needs a more specific selector.
    """
    try:
        prompt = page.get_by_text(_INPROGRESS_PROMPT_RE)
        if await prompt.count() == 0 or not await prompt.first.is_visible():
            return False
        await snap(page, "INPROGRESS_prompt")
        # "No" keeps us on the current page. Prefer the exact-named button; fall back to
        # any visible button whose text is just "No".
        no_btn = page.get_by_role("button", name="No", exact=True)
        if await no_btn.count() == 0:
            no_btn = page.locator("button", has_text=re.compile(r"^\s*No\s*$", re.I))
        await no_btn.first.click(timeout=5000)
        await page.wait_for_timeout(400)
        print("  Dismissed the EMR 'In Progress' prompt (clicked No).")
        return True
    except Exception as e:
        # If it's up but we couldn't clear it, say so and leave it — the batch's existing
        # error handling / circuit breaker take over, and the snap above is captured.
        print(f"  Note: couldn't auto-dismiss the In Progress prompt: "
              f"{str(e).splitlines()[0]}")
        return False


async def open_dashboard(page: Page) -> bool:
    """Go to the dashboard with the roster loaded, recovering from an expired session.

    The batch's #1 failure mode is the EMR session timing out mid-run: every later
    page.goto() silently lands on the login screen, where there is no employee row and
    no search box — so the next click sits for its full 30s timeout and dies. Five of
    those in a row trips the circuit breaker and the rest of the batch never runs.
    (Exactly how a 77-row batch stopped at 35.)

    So: detect the login screen, pause for Dane to log back in, and retry. Returns
    True once the roster is actually on screen.
    """
    for _ in range(4):
        await page.goto(BASE_URL)
        await page.wait_for_load_state("networkidle")
        # Clear the new "In Progress" modal if it popped on load — it overlays the
        # roster and would block the next click. It can also render a beat after
        # networkidle, so we try again once the roster is attached.
        await dismiss_in_progress_prompt(page)
        try:
            await page.wait_for_selector(_NAME_SEL, state="attached", timeout=15000)
            await dismiss_in_progress_prompt(page)
            return True
        except Exception:
            pass
        if await _looks_logged_out(page):
            popup("Your ATI session has logged out.\n\nLog back in in the browser "
                  "(and make sure the worksite is selected), then click OK to "
                  "carry on with the batch — it picks up where it left off.",
                  title="EMR AutoMate — session expired")
            continue  # retry the navigation after re-login
        await page.wait_for_timeout(1500)  # transient slow load — try once more
    return False


async def fill_encounter(page: Page, ENCOUNTER):
    """Fill and save a single coaching encounter (assumes already logged in)."""
    # ── BACK TO DASHBOARD ──────────────────────
    # Reset to the home screen so the employee search box is available. Guarded: an
    # expired session must pause for re-login, not burn a 30s click timeout per row.
    if not await open_dashboard(page):
        raise RuntimeError("The dashboard/roster didn't load — session or connection. "
                           "Nothing was entered for this row.")
    await snap(page, "01_dashboard")

    # ── FIND EMPLOYEE ──────────────────────────
    # The dashboard preloads the FULL roster into .employee-list, so we locate the
    # person directly by name. The search box is only a client-side filter and its
    # matching doesn't handle the "Last, First" format, so we don't rely on it —
    # it's just a fallback to narrow the list if the direct match isn't found.
    full_name = ENCOUNTER["employee_search"].strip()
    print(f"Locating employee: {ph(full_name)}")

    target = await locate_employee(page, full_name)
    await target.scroll_into_view_if_needed()
    await target.click()
    await page.wait_for_load_state("networkidle")
    # The Employee Overview keeps loading (cases / follow-ups / portfolio) after
    # networkidle and re-renders, so let it settle before clicking Add Case.
    await page.wait_for_timeout(2500)
    # The "In Progress" prompt can also surface here, over the employee overview —
    # clear it before reaching for Add Case.
    await dismiss_in_progress_prompt(page)
    print("Employee selected.")
    await snap(page, "03_employee_selected")

    # ── ADD CASE ───────────────────────────────
    add_case_btn = page.locator("button:has-text('+ Add Case')")
    await add_case_btn.wait_for(state="visible", timeout=20000)

    # The EMR DISABLES "+ Add Case" for an employee who already has an In Progress
    # case. Verified on the 2026-07-29 run, from the capture taken BEFORE the click:
    # all 4 rows that failed had `<button ... disabled="">+ Add Case</button>` plus an
    # "In Progress" badge, and all 52 rows that succeeded had neither.
    #
    # A disabled button is not a slow one, so the old force-click fallback was actively
    # harmful: force=True skips the actionability checks and clicks a disabled button,
    # which does nothing, silently. The modal never opened and the tile click below then
    # burned its full 30s default timeout waiting for markup that was never coming —
    # 2 minutes of the run spent to produce four "Timeout 30000ms exceeded" notes that
    # named neither the cause nor the fix. Wait for *enabled*, then say what's wrong.
    for _ in range(16):                       # 8s grace for a slow render
        if await add_case_btn.is_enabled():
            break
        await page.wait_for_timeout(500)
    else:
        await snap(page, "ALREADY_INPROGRESS")
        raise AlreadyInProgress(
            "'+ Add Case' is disabled for this employee — the EMR does that when they "
            "already have an In Progress case. Finalize or delete that draft in the "
            "EMR, then re-run with --resume. Nothing was entered for this row."
        )

    try:
        await add_case_btn.click(timeout=8000)
    except Exception:
        # Enabled but something is sitting over it (a late re-render). Force is
        # legitimate here — the button can actually receive the click.
        print("  Add Case retry (force-click)...")
        await add_case_btn.click(force=True)
    await page.wait_for_timeout(800)
    await snap(page, "04_add_case_modal")

    # In the "Select Assessment Type" modal, click the Coaching Encounter tile.
    # Each option is a `.assessment-type-container` div — click the container so the
    # selection registers (clicking just the text doesn't always trigger it).
    # Bounded well under the 30s default: if the modal isn't up by now it isn't coming,
    # and a clear message beats half a minute of waiting to say "timeout".
    tile = page.locator(".assessment-type-container", has_text="Coaching Encounter")
    try:
        await tile.click(timeout=10000)
    except Exception:
        raise RuntimeError(
            "The 'Select Assessment Type' modal never opened after '+ Add Case' "
            "(no .assessment-type-container on the page) — see the 04 debug capture."
        )
    await page.wait_for_timeout(400)

    # Confirm with the modal's "Add Case" button. The page's OTHER button reads
    # "+ Add Case", so match the exact name to avoid clicking that one (which sits
    # behind the modal overlay and blocks the click).
    confirm_btn = page.get_by_role("button", name="Add Case", exact=True)
    await confirm_btn.click()
    await page.wait_for_load_state("networkidle")
    print("Coaching Encounter form opened.")
    await snap(page, "05_step1_form")

    # ── STEP 1: ENCOUNTER DETAILS ──────────────
    print("Filling Step 1: Encounter Details...")

    # The form loads behind a spinner — wait for the date field before acting.
    await page.locator(
        "input.form-field-input[placeholder='Date of Encounter']"
    ).wait_for(state="visible", timeout=20000)

    await fill_date(page, ENCOUNTER["date_of_encounter"])
    await click_radio(page, ENCOUNTER["encounter_type"])

    # Department/Division/Category/Shift are optional — non-blocking so an
    # unmatched option doesn't stop the encounter (these are ati-react-selects
    # targeted by their field label).
    if ENCOUNTER["department"]:
        await react_select(page, "Department", ENCOUNTER["department"], required=False)
    if ENCOUNTER["division"]:
        await react_select(page, "Division", ENCOUNTER["division"], required=False)
    if ENCOUNTER["category"]:
        await react_select(page, "Category", ENCOUNTER["category"], required=False)
    if ENCOUNTER["shift"]:
        await react_select(page, "Shift", ENCOUNTER["shift"], required=False)

    await snap(page, "05b_step1_filled")

    # Click Next
    next_btn = page.locator("button:has-text('Next')")
    await next_btn.click()
    await page.wait_for_load_state("networkidle")
    print("Moved to Step 2.")
    await page.wait_for_timeout(800)
    await snap(page, "06_step2_form")

    # ── STEP 2: COACHING ASSESSMENT ────────────
    print("Filling Step 2: Coaching Assessment...")

    # Select coaching type. The field label is the one-word "CoachingType".
    # Non-blocking so an unmatched value still drafts (Dane completes at finalize).
    await react_select(page, "CoachingType", ENCOUNTER["coaching_type"], required=False)
    await page.wait_for_timeout(500)  # wait for detail checkboxes to render

    # Look up the checkbox UUID map for this coaching type
    uuid_map = CHECKBOX_UUID_MAP.get(ENCOUNTER["coaching_type"], {})
    if not uuid_map:
        print(f"  Note: checkbox UUIDs not yet mapped for '{ENCOUNTER['coaching_type']}'")

    for label in ENCOUNTER["coaching_detail_types"]:
        uuid = uuid_map.get(label)
        if uuid:
            await tick_checkbox(page, uuid)
            print(f"  Checked: {label}")
        else:
            print(f"  WARNING: No UUID mapped for '{label}' — skipping")

    # Description (best-effort — selector unverified; don't let it block the draft)
    if ENCOUNTER["description"]:
        try:
            desc_area = page.locator("textarea[name='description']")
            await desc_area.fill(ENCOUNTER["description"], timeout=6000)
        except Exception as e:
            print(f"  WARNING: couldn't fill description: {str(e).splitlines()[0]}")

    # What Prompted Coaching (label guessed; non-blocking so we can still reach the
    # review/save step and capture the real label if this one is off)
    await react_select(page, "What Prompted Coaching", ENCOUNTER["what_prompted"],
                       required=False)
    await snap(page, "07_filled_ready_to_save")

    # ── SAVE ───────────────────────────────────
    # Returns a status the caller uses to drive the batch/loop:
    #   "saved" · "skipped" · "quit"
    if SAVE_MODE == "draft":
        await _save_in_progress(page)
        return "saved"
    if SAVE_MODE == "final":
        await _do_save(page)
        return "saved"

    # SAVE_MODE == "review"
    print("\n─────────────────────────────────────────")
    print("REVIEW: the form is filled. Check the browser window, then:")
    print("  [Enter]   = save this encounter (finalize)")
    print("  s + Enter = skip it (don't save), go to the next")
    print("  q + Enter = quit")
    print("─────────────────────────────────────────")
    choice = input("Choice: ").strip().lower()
    if choice == "q":
        return "quit"
    if choice == "s":
        print("Skipped — not saved.")
        return "skipped"
    await _do_save(page)
    return "saved"


async def _save_in_progress(page: Page):
    """Click 'Save in progress' to store a DRAFT (finalize later in the EMR)."""
    btn = page.get_by_role("button", name="Save in progress")
    await btn.click()
    await page.wait_for_load_state("networkidle")
    print("✓ Saved as draft (Save in progress) — review/finalize in InProgress.")


async def _do_save(page: Page):
    """Click the final Save button (finalizes the encounter)."""
    save_btn = page.locator("button.btn-primary:has-text('Save')")
    await save_btn.click()
    await page.wait_for_load_state("networkidle")
    print("✓ Encounter saved (finalized).")


# ─────────────────────────────────────────────
# CSV BATCH INPUT
# ─────────────────────────────────────────────

# CSV column order. `details` is semicolon-separated (so commas in names/notes
# don't collide). `employee` is "Last, First" and must be quoted in the CSV.
CSV_COLUMNS = [
    "employee", "date", "encounter_type", "department", "division",
    "category", "shift", "coaching_type", "details", "description", "what_prompted",
]


def _echo(value):
    """Render a rejected value for an error message, without leaking PHI.

    Dropdown values are short ("Frame Weld", "Line Lead"), so echoing them is safe and
    is what makes an error actionable. But when a row's columns are misaligned — an
    unquoted comma in the description shifts everything left — a whole clinical note
    can land in a dropdown column, and echoing *that* would put PHI into a message
    Claude and bug reports get to see.

    So: short values echo, long ones are suppressed with the diagnosis they actually
    imply, which is more useful than the text anyway.
    """
    v = str(value or "")
    if len(v) <= 40:
        return f"'{v}'"
    return (f"[{len(v)} characters of free text — this row's columns are almost "
            f"certainly misaligned, likely an unquoted comma in the description]")


def _exact_option(field, value, col, line_no, errs):
    """Match `value` against an EMR dropdown's options. Returns the canonical option,
    or None.

    Case-insensitive, so 'line lead' becomes 'Line Lead'. "Select" is the EMR's own
    empty-choice placeholder and means blank. Appends to `errs` when the value is
    unrecognised — pass an empty list to probe without recording an error (the caller
    may want to try the field mapper first).
    """
    value = (value or "").strip()
    if not value or value.casefold() == "select":
        return None
    options = FIELD_OPTIONS.get(field, [])
    if not options:
        return value  # no options file → don't block the run
    canonical = {o.casefold(): o for o in options}
    if value.casefold() in canonical:
        return canonical[value.casefold()]
    errs.append(f"Row {line_no}: {col} {_echo(value)} is not valid. "
                f"Use one of: {' | '.join(options)}  (or leave it blank)")
    return None


def row_to_encounter(row, line_no):
    """Convert one CSV row to an ENCOUNTER dict. Returns (encounter, [errors])."""
    errs = []

    def get(col):
        return (row.get(col) or "").strip()

    employee = get("employee")
    if not employee:
        errs.append(f"Row {line_no}: missing employee name.")

    date_val = get("date") or date.today().strftime("%m/%d/%Y")

    encounter_type = get("encounter_type") or ENCOUNTER_TYPES[0]
    if encounter_type not in ENCOUNTER_TYPES:
        errs.append(f"Row {line_no}: encounter_type {_echo(encounter_type)} is not valid. "
                    f"Use one of: {' | '.join(ENCOUNTER_TYPES)}")

    coaching_type = get("coaching_type")
    if coaching_type not in COACHING_TYPE_UUIDS:
        errs.append(f"Row {line_no}: coaching_type {_echo(coaching_type)} is not valid. "
                    f"Use one of: {' | '.join(COACHING_TYPE_UUIDS)}")

    detail_set = CHECKBOX_UUID_MAP.get(coaching_type, {})
    details = [d.strip() for d in get("details").split(";") if d.strip()]
    for d in details:
        if d not in detail_set:
            valid = ", ".join(detail_set) if detail_set else "(this type has no detail options)"
            errs.append(f"Row {line_no}: detail {_echo(d)} is not valid for "
                        f"{coaching_type or '(no type)'}. Valid: {valid}")

    what_prompted = get("what_prompted") or WHAT_PROMPTED_OPTIONS[0]
    if what_prompted not in WHAT_PROMPTED_OPTIONS:
        errs.append(f"Row {line_no}: what_prompted {_echo(what_prompted)} is not valid. "
                    f"Use one of: {' | '.join(WHAT_PROMPTED_OPTIONS)}")

    # ── Dropdowns: Department / Division / Category / Shift ──
    # Category and Shift are plain dropdowns: exact value or blank.
    dropdowns = {}
    for col in ("category", "shift"):
        dropdowns[col] = _exact_option(DROPDOWN_COLUMNS[col], get(col), col, line_no, errs)

    # Department and Division are different: a work area may arrive the way Dane
    # says it out loud — "Finishers", "THT", "line lead, weld", "station 85" — and
    # emr_field_map exists precisely to turn that phrasing into the EMR's vocabulary.
    # So anything that isn't already an exact option goes through the mapper rather
    # than being rejected. Expecting an upstream tool to memorise 49 department names
    # is what produced 71 near-miss values in a single batch.
    department = _exact_option("Department", get("department"), "department", line_no, [])
    division = _exact_option("Division", get("division"), "division", line_no, [])

    if get("department") and not department:
        mapped_dept, mapped_div = emr_field_map.resolve(get("department"))
        department = mapped_dept or None
        # The mapper reads the line out of the same phrase ("line lead, weld" -> Weld),
        # so let it supply the division — but never overwrite one Dane gave explicitly.
        if not division:
            division = mapped_div or None
        if not department:
            errs.append(f"Row {line_no}: department {_echo(get('department'))} is not valid "
                        f"and could not be mapped to an EMR department. Use one of: "
                        f"{' | '.join(FIELD_OPTIONS.get('Department', []))}  "
                        f"(or leave it blank)")

    if get("division") and not division:
        _, mapped_div = emr_field_map.resolve(get("division"))
        division = mapped_div or None
        if not division:
            errs.append(f"Row {line_no}: division {_echo(get('division'))} is not valid and "
                        f"could not be mapped. Use one of: "
                        f"{' | '.join(FIELD_OPTIONS.get('Division', []))}  "
                        f"(or leave it blank)")

    dropdowns["department"] = department
    dropdowns["division"] = division

    encounter = {
        "employee_search": employee,
        "date_of_encounter": date_val,
        "encounter_type": encounter_type,
        "department": dropdowns["department"],
        "division": dropdowns["division"],
        "category": dropdowns["category"],
        "shift": dropdowns["shift"],
        "coaching_type": coaching_type,
        "coaching_detail_types": details,
        "description": get("description"),
        "what_prompted": what_prompted,
    }
    return encounter, errs


def load_encounters_csv(path):
    """Read the CSV into (encounters, errors). Header is row 1; data starts at 2."""
    encounters, errors = [], []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for line_no, row in enumerate(reader, start=2):
            # Skip fully blank lines
            if not any((v or "").strip() for v in row.values()):
                continue
            enc, row_errs = row_to_encounter(row, line_no)
            encounters.append(enc)
            errors.extend(row_errs)
    return encounters, errors


def batch_warnings(encounters):
    """Soft warnings about a validated batch — things that pass validation but are
    worth an eyeball. Returns a list of strings (empty if all clear).

    These are NOT errors. A batch really can be all one coaching type — a sweep day
    built in encounter_builder legitimately is. But a uniform type has also meant a
    tool silently defaulting it (that once put the wrong type on 80 records), so it
    gets said out loud here, before entry, instead of in the medical record.
    """
    from collections import Counter
    warns = []
    n = len(encounters)
    if n == 0:
        return warns

    types = Counter(e.get("coaching_type") or "(blank)" for e in encounters)
    top_type, top_n = types.most_common(1)[0]
    if n >= 5 and top_n / n >= 0.8:
        warns.append(
            f"{top_n} of {n} encounters are '{top_type}'. Fine if you built them as "
            f"one sweep - if not, check before entering.")

    blank_shift = sum(1 for e in encounters if not e.get("shift"))
    blank_cat = sum(1 for e in encounters if not e.get("category"))
    if blank_shift == n and n >= 5:
        warns.append(f"All {n} encounters have a blank Shift.")
    if blank_cat == n and n >= 5:
        warns.append(f"All {n} encounters have a blank Category.")
    return warns


def _last_run_saved_keys():
    """{(employee, date, coaching_type)} that the MOST RECENT run confirmed saved.

    Keyed by content, not by row number: a resumed encounters.csv is renumbered, so
    row indices from an older run would point at the wrong people. Content keys also
    make --resume idempotent — run it twice and the second pass finds those rows
    already gone, instead of eating a different 35.
    """
    if not os.path.exists(ENCOUNTER_LOG_CSV):
        return set(), None
    with open(ENCOUNTER_LOG_CSV, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("run_started")]
    if not rows:
        return set(), None
    last = max(r["run_started"] for r in rows)
    keys = {(r["employee"], r["date"], r["coaching_type"])
            for r in rows if r["run_started"] == last and r["status"] == "saved"}
    return keys, last


def resume_batch():
    """Rewrite encounters.csv to only the rows the last run did NOT save.

    A run can stop early — a timed-out session, the circuit breaker — leaving the
    batch half entered. Re-running the same file would draft the saved ones a second
    time, so this drops them and leaves the remainder.

    Only rows the audit log records as CONFIRMED saved are dropped. A row that errored
    is kept: the debug captures show those die before the form is reached, so they
    entered nothing. Counts only are printed — never a name.
    """
    if not os.path.exists(ENCOUNTERS_CSV):
        sys.exit("No encounters.csv to resume.")

    saved_keys, run_started = _last_run_saved_keys()
    if not saved_keys:
        print("The audit log has no confirmed-saved rows for the last run.")
        print("Nothing to drop — encounters.csv is left exactly as it is.")
        return

    encounters, errors = load_encounters_csv(ENCOUNTERS_CSV)
    if errors:
        sys.exit(f"encounters.csv has {len(errors)} validation problem(s) — "
                 f"fix those first (.\\Run-Encounters.ps1 -Check).")

    # Raw CSV rows, skipping blanks exactly as load_encounters_csv does, so index i
    # of `raw` is the same encounter as index i of `encounters`.
    with open(ENCOUNTERS_CSV, newline="", encoding="utf-8-sig") as fh:
        raw = [r for r in csv.DictReader(fh)
               if any((v or "").strip() for v in r.values())]
    if len(raw) != len(encounters):
        sys.exit("Couldn't line up encounters.csv rows with the validator — "
                 "not touching the file.")

    keep, dropped = [], 0
    for row, enc in zip(raw, encounters):
        key = (enc.get("employee_search") or "",
               enc.get("date_of_encounter") or "",
               enc.get("coaching_type") or "")
        if key in saved_keys:
            dropped += 1
        else:
            keep.append(row)

    print(f"Last run: {run_started}")
    print(f"  confirmed saved in that run : {len(saved_keys)}")
    print(f"  rows in encounters.csv      : {len(raw)}")
    print(f"  dropping (already saved)    : {dropped}")
    print(f"  keeping (still to enter)    : {len(keep)}")

    if not keep:
        print("\nEverything in this batch is already saved. Nothing left to enter.")
        return
    if not dropped:
        print("\nNone of these rows match the last run's saved list — file unchanged.")
        return

    with open(ENCOUNTERS_BAK_CSV, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(raw)
    with open(ENCOUNTERS_CSV, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(keep)

    print(f"\nFull batch backed up to {os.path.basename(ENCOUNTERS_BAK_CSV)}.")
    print(f"encounters.csv now holds the {len(keep)} row(s) still to enter.")
    print("\nEnter them with:  .\\Run-Encounters.ps1")


def prepare_batch():
    """If encounters.csv exists, load + validate + confirm it.

    Returns a list of encounters for batch mode, or None to fall back to
    interactive entry. Raises SystemExit if the CSV has validation errors.
    """
    if not os.path.exists(ENCOUNTERS_CSV):
        return None

    encounters, errors = load_encounters_csv(ENCOUNTERS_CSV)
    if not encounters:
        print("encounters.csv is empty — switching to manual entry.")
        return None

    print(f"\nFound {len(encounters)} encounter(s) in encounters.csv:")
    for i, enc in enumerate(encounters, 1):
        det = ", ".join(enc["coaching_detail_types"]) or "—"
        print(f"  {i}. {ph(enc['employee_search'])}  |  {enc['coaching_type'] or '(no type)'}"
              f"  |  {enc['date_of_encounter']}  |  {det}")

    if errors:
        print("\n⚠ Fix these problems in encounters.csv before entering:")
        for e in errors:
            print(f"   - {e}")
        print("\nNothing was entered. Correct the CSV and run again.")
        raise SystemExit(1)

    # ── LAST-GATE COMPOSITION SUMMARY ──────────
    # The confirmation used to show only a count, so a batch where every coaching type
    # had been defaulted the same looked identical to a good one. Show WHAT is about to
    # be entered — the coaching-type breakdown and date range — plus any soft warnings,
    # right in the popup. This is the final human check before anything is written.
    from collections import Counter
    types = Counter(e["coaching_type"] or "(none)" for e in encounters)
    dates = sorted({e["date_of_encounter"] for e in encounters if e["date_of_encounter"]})
    warns = batch_warnings(encounters)

    summary_lines = [f"About to enter {len(encounters)} encounter(s)."]
    if dates:
        span = dates[0] if len(dates) == 1 else f"{dates[0]} – {dates[-1]}"
        summary_lines.append(f"Dates: {span}")
    summary_lines.append("")
    summary_lines.append("Coaching types:")
    for t, c in types.most_common():
        summary_lines.append(f"   {c:>3}  {t}")
    if warns:
        summary_lines.append("")
        summary_lines.append("⚠ CHECK BEFORE ENTERING:")
        for w in warns:
            summary_lines.append(f"   • {w}")
    summary_lines.append("")
    summary_lines.append("Enter them into the EMR now?")

    # Print it too (redaction-aware) so it's in the run log.
    print("\n" + "\n".join(summary_lines))

    if not popup("\n".join(summary_lines), yes_no=True,
                 title="EMR AutoMate — confirm this batch"):
        print("Okay — nothing entered.")
        return None
    return encounters


async def run():
    # Decide the source of encounters BEFORE opening the browser, so a broken CSV
    # is caught (and the user confirms the batch) without launching anything.
    batch = prepare_batch()  # list of encounters, or None for interactive entry

    async with async_playwright() as p:
        # Persistent profile: remembers your login AND your worksite (org)
        # selection between runs, the same way your normal browser does.
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            slow_mo=100,
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # ── LOGIN / ORG (manual; remembered next time) ──
        print("Opening browser...")
        await page.goto(BASE_URL)
        await page.wait_for_load_state("networkidle")

        popup(
            "Log in to ATI in the browser if it asks, and make sure the correct "
            "worksite (e.g. Navarre) is selected at the top.\n\n"
            "Then click OK to continue.",
            title="EMR AutoMate — ready to start?",
        )
        await page.wait_for_load_state("networkidle")

        if batch is not None:
            await run_batch(page, batch)
        else:
            await run_interactive(page)

        print("\nClosing browser. Goodbye.")
        await context.close()


async def run_batch(page: Page, encounters):
    """Enter a fixed list of encounters from the CSV, reviewing each in turn."""
    run_started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── PRE-FLIGHT ─────────────────────────────
    # Check every name against the roster before entering anything, so a nickname the
    # EMR doesn't know surfaces now — not on encounter 61 of 80.
    print("\nChecking every name against the roster first...")
    matched, problems = await preflight_names(page, encounters)

    # preflight_names returns problems == "roster-empty" when the dashboard roster
    # never rendered. That is NOT a batch of bad names — it's a load/login/worksite
    # problem — so don't offer to "skip them" and enter nothing.
    if problems == "roster-empty":
        print("\n⚠ The employee roster didn't load — the dashboard came back empty.")
        print("  This is NOT a problem with your names. Nothing was entered.")
        popup(
            "The employee roster didn't load, so no names could be checked.\n\n"
            "This is a page-load problem, not a problem with your encounters. "
            "Usually it means the browser isn't logged in yet, or the worksite "
            "(e.g. Navarre) isn't selected at the top.\n\n"
            "Fix that in the browser, then run the batch again. Nothing was entered.",
            title="EMR AutoMate — roster didn't load")
        return

    unmatched_names = {p[0] for p in problems}

    nicknames = {n: v for n, v in matched.items() if v[1] != "exact"}
    if nicknames:
        print(f"\n{len(nicknames)} name(s) resolved via nickname/loose match:")
        for spoken, (formal, how) in nicknames.items():
            print(f"  {ph(spoken)}  ->  {ph(formal)}   ({how})")

    if problems:
        print(f"\n⚠ {len(problems)} name(s) could NOT be resolved:")
        for spoken, why, options in problems:
            if options:
                print(f"  {ph(spoken)}  — {why}: {' | '.join(ph(o) for o in options)}")
            else:
                print(f"  {ph(spoken)}  — {why}")

        affected = sum(1 for e in encounters
                       if (e.get("employee_search") or "").strip()
                       in {p[0] for p in problems})
        print(f"\n  {affected} of {len(encounters)} encounter(s) use those names.")
        print("  Fix them in encounters.csv (use the full formal name), or continue and")
        print("  they'll be skipped.")

        if not popup(f"{len(problems)} name(s) couldn't be matched to the roster, "
                     f"affecting {affected} of {len(encounters)} encounter(s).\n\n"
                     f"Continue anyway and skip them?\n"
                     f"(No = stop, so you can fix encounters.csv first.)",
                     yes_no=True, title="EMR AutoMate — unmatched names"):
            print("Stopped. Nothing was entered — fix the names and run again.")
            return
    else:
        print(f"All {len(matched)} name(s) matched the roster.")

    print(f"\nEntering {len(encounters)} encounter(s) from encounters.csv.")
    tally = {"saved": 0, "skipped": 0, "error": 0}
    consecutive_errors = 0
    CIRCUIT_BREAK = 5  # stop if this many form-fills fail back-to-back
    for i, encounter in enumerate(encounters, 1):
        name = (encounter.get("employee_search") or "").strip()
        ctype = encounter.get("coaching_type") or ""
        edate = encounter.get("date_of_encounter") or ""

        def record(status, note=""):
            match_info = matched.get(name)
            matched_to = match_info[0] if match_info else ""
            log_encounter(run_started, i, name, matched_to, ctype, edate, status, note)

        print(f"\n══ Encounter {i} of {len(encounters)}: {ph(name)} ══")

        # A name the pre-flight already couldn't resolve: don't attempt it (it would
        # just error on the dashboard, as all 14 did). Log and move on.
        if name in unmatched_names:
            why = next((p[1] for p in problems if p[0] == name), "name not matched")
            print(f"  Skipped — {why}. Fix the name in encounters.csv.")
            record("name-unmatched", why)
            tally["skipped"] += 1
            continue

        try:
            status = await fill_encounter(page, encounter)
        except AlreadyInProgress as e:
            # Their EMR state, not a failure of this run: don't count it as an error
            # and don't let a cluster of them trip the circuit breaker.
            print(f"  Skipped — {e}")
            record("already-in-progress", str(e))
            tally["skipped"] += 1
            consecutive_errors = 0
            continue
        except Exception as e:
            # Auto-continue rather than block on a dialog. Everything is a draft and now
            # audited, so an unattended batch should keep going, not freeze for hours on
            # a popup nobody is there to click. The failure is captured for review.
            msg = str(e).splitlines()[0] if str(e) else e.__class__.__name__
            print(f"  ⚠ Error — skipped and logged: {ph(msg)}")
            await snap(page, "ERROR_state")
            record("error", msg)
            tally["error"] += 1
            consecutive_errors += 1
            # A run of back-to-back failures means something systemic (login expired, a
            # changed selector) — not bad data in one row. Stop rather than churn through
            # the rest generating identical errors.
            if consecutive_errors >= CIRCUIT_BREAK:
                print(f"\n⚠ {CIRCUIT_BREAK} encounters failed in a row — stopping. This is"
                      f" usually login expiring or the EMR changing. The rest are"
                      f" untouched; fix the cause and re-run.")
                break
            continue

        consecutive_errors = 0
        if status == "quit":
            print("Stopping the batch here.")
            record("quit", "user stopped the batch")
            break
        record(status)
        tally[status] = tally.get(status, 0) + 1

    # ── SUMMARY ────────────────────────────────
    print("\n── Batch complete ──")
    print(f"  saved:   {tally.get('saved', 0)}")
    print(f"  skipped: {tally.get('skipped', 0)}  (unmatched names / already In Progress"
          f" / your skips)")
    print(f"  errors:  {tally.get('error', 0)}")
    print(f"\n  Full audit log: {os.path.basename(ENCOUNTER_LOG_CSV)}")
    print(f"  Review it redacted with:  python {os.path.basename(__file__)} --audit")


async def run_interactive(page: Page):
    """Prompt for and enter encounters one at a time until the user stops."""
    print("Continuing — enter as many encounters as you like.")
    while True:
        encounter = prompt_encounter()
        try:
            status = await fill_encounter(page, encounter)
        except Exception as e:
            print(f"\n⚠ Something went wrong filling this encounter: {e}")
            await snap(page, "ERROR_state")
            print("  The browser is still open and you're still logged in.")
            print("  A screenshot + page HTML of the failure was saved to ./debug")
            status = None

        if status == "quit":
            break
        if not popup("Do another encounter?", yes_no=True):
            break


async def run_capture_fields(employee_name):
    """Open a fresh Coaching Encounter form for one employee and capture every option
    in the Department / Division / Category / Shift dropdowns (read-only, no save).
    Writes emr_field_options.json so we can map source data -> the real EMR options.
    """
    import json
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR, headless=False, slow_mo=100)
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(BASE_URL)
            await page.wait_for_load_state("networkidle")
            popup("Log in / confirm Navarre if needed, then click OK to capture the "
                  "encounter dropdown options.", title="EMR AutoMate — field capture")
            await page.wait_for_load_state("networkidle")

            full_name = employee_name.strip()
            print(f"Locating {ph(full_name)}...")
            rows = page.locator(".employee-list .details", has_text=full_name)
            if await rows.count() == 0:
                last = full_name.split(",")[0].strip()
                box = page.locator("input[placeholder='Search Employee or Identifier']")
                await box.click()
                await box.fill(last)
                await page.wait_for_timeout(1200)
                rows = page.locator(".employee-list .details", has_text=full_name)
            if await rows.count() == 0:
                print(f"Couldn't find '{ph(full_name)}'. Try a different name.")
                return
            await rows.first.scroll_into_view_if_needed()
            await rows.first.click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2500)

            # Add Case -> Coaching Encounter (same flow the drafts use)
            btn = page.locator("button:has-text('+ Add Case')")
            await btn.wait_for(state="visible", timeout=20000)
            try:
                await btn.click(timeout=8000)
            except Exception:
                await btn.click(force=True)
            await page.wait_for_timeout(800)
            await page.locator(".assessment-type-container",
                               has_text="Coaching Encounter").click()
            await page.wait_for_timeout(400)
            await page.get_by_role("button", name="Add Case", exact=True).click()
            await page.wait_for_load_state("networkidle")
            await page.locator(
                "input.form-field-input[placeholder='Date of Encounter']"
            ).wait_for(state="visible", timeout=20000)
            await page.wait_for_timeout(800)

            options = {}
            for label in ("Department", "Division", "Category", "Shift"):
                try:
                    control = page.locator(
                        f"xpath=//label[normalize-space(.)='{label}']"
                        f"/following-sibling::div[1]"
                        f"//div[contains(@class,'ati-react-select__control')]").first
                    await control.click(timeout=6000)
                    await page.wait_for_timeout(600)
                    opts = await page.locator(".ati-react-select__option").all_inner_texts()
                    options[label] = [o.strip() for o in opts if o.strip()]
                    print(f"  {label}: {len(options[label])} options")
                    await snap(page, f"FIELD_{label}")
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(300)
                except Exception as e:
                    print(f"  WARNING: couldn't read {label}: {str(e).splitlines()[0]}")
                    options[label] = []
                    try:
                        await page.keyboard.press("Escape")
                    except Exception:
                        pass

            out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "emr_field_options.json")
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(options, fh, indent=2)
            print(f"\nSaved dropdown options to {out}")
            popup("Captured the 4 dropdown option lists to emr_field_options.json.\n\n"
                  "Click OK to close.", title="EMR AutoMate — field capture done")
        finally:
            await context.close()


async def run_capture_assessment(employee_name, assessment_label="Physical Assessment"):
    """Open a fresh assessment case for one employee and capture its FIRST screen —
    read-only, nothing saved.

    Same navigation as a coaching draft (locate employee -> + Add Case -> the "Select
    Assessment Type" modal), but instead of the Coaching Encounter tile it clicks the
    one whose text contains `assessment_label` (default "Physical Assessment"). The
    scrubbed first-screen HTML lands in ./debug for field mapping.

    We don't yet know the exact tile labels or the form's ready-signal, so this mode
    MEASURES both rather than guessing: it prints the modal's tile labels (static UI
    strings — safe) and the first screen's field labels, and snaps each step. No save
    button is ever touched.
    """
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR, headless=False, slow_mo=100)
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(BASE_URL)
            await page.wait_for_load_state("networkidle")
            popup("Log in / confirm the worksite if needed, then click OK to capture "
                  f"the '{assessment_label}' first screen (nothing is saved).",
                  title="EMR AutoMate — assessment capture")
            await page.wait_for_load_state("networkidle")

            full_name = employee_name.strip()
            print(f"Locating {ph(full_name)}...")
            rows = page.locator(".employee-list .details", has_text=full_name)
            if await rows.count() == 0:
                last = full_name.split(",")[0].strip()
                box = page.locator("input[placeholder='Search Employee or Identifier']")
                await box.click()
                await box.fill(last)
                await page.wait_for_timeout(1200)
                rows = page.locator(".employee-list .details", has_text=full_name)
            if await rows.count() == 0:
                print(f"Couldn't find '{ph(full_name)}'. Try a different name.")
                return
            await rows.first.scroll_into_view_if_needed()
            await rows.first.click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2500)

            # + Add Case -> "Select Assessment Type" modal
            btn = page.locator("button:has-text('+ Add Case')")
            await btn.wait_for(state="visible", timeout=20000)
            try:
                await btn.click(timeout=8000)
            except Exception:
                await btn.click(force=True)
            await page.wait_for_timeout(800)
            await snap(page, "ASSESS_00_add_case_modal")

            # List every case-type tile so we KNOW the exact labels (open question in
            # TODO.md) instead of guessing them. These are static UI strings.
            tiles = page.locator(".assessment-type-container")
            labels = [t.strip() for t in await tiles.all_inner_texts() if t.strip()]
            print(f"Assessment-type tiles ({len(labels)}):")
            for lbl in labels:
                print(f"  - {lbl}")

            tile = page.locator(".assessment-type-container", has_text=assessment_label)
            if await tile.count() == 0:
                print(f"\nNo tile matches '{assessment_label}'. Re-run with one of the "
                      f"labels listed above, e.g.:\n"
                      f'  python ati_coaching_encounter.py --capture-assessment '
                      f'"Last, First" "<label>"')
                return
            await tile.first.click()
            await page.wait_for_timeout(400)
            await page.get_by_role("button", name="Add Case", exact=True).click()
            await page.wait_for_load_state("networkidle")
            # We don't know this form's ready-signal, so settle on networkidle + a pause
            # rather than waiting on a coaching-specific field that may not exist here.
            await page.wait_for_timeout(2500)
            print(f"'{assessment_label}' first screen opened.")
            await snap(page, "ASSESS_01_step1_form")

            # Field labels on the first screen — static UI, safe to print, and the
            # starting point for mapping the form.
            field_labels = [t.strip()
                            for t in await page.locator("form label, .form-field label")
                                                .all_inner_texts()
                            if t.strip()]
            if field_labels:
                print(f"\nFirst-screen field labels ({len(field_labels)}):")
                for lbl in field_labels:
                    print(f"  - {lbl}")

            print("\nCaptured the scrubbed first screen to ./debug (ASSESS_*.html). "
                  "Nothing was saved.")
            popup(f"Captured the '{assessment_label}' first screen to ./debug.\n\n"
                  "Nothing was saved. Click OK to close.",
                  title="EMR AutoMate — assessment capture done")
        finally:
            await context.close()


def review_audit(last_run_only=True):
    """Print the encounter audit log. Names go through ph()/pd(), so on a captured
    stdout (an assistant, a pipe) they show as 'Employee #1' — Dane sees the real names
    in his own terminal. This is how a run can be reviewed without handing over PHI.
    """
    if not os.path.exists(ENCOUNTER_LOG_CSV):
        print(f"No audit log yet ({os.path.basename(ENCOUNTER_LOG_CSV)} doesn't exist).")
        return
    with open(ENCOUNTER_LOG_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("Audit log is empty.")
        return

    if last_run_only:
        latest = rows[-1]["run_started"]
        rows = [r for r in rows if r["run_started"] == latest]
        print(f"Most recent run: {latest}  ({len(rows)} encounter(s))\n")
    else:
        print(f"All runs: {len(rows)} encounter(s) total\n")

    from collections import Counter
    tally = Counter(r["status"] for r in rows)

    # Problems first — that's what a review is for.
    problems = [r for r in rows if r["status"] not in ("saved",)]
    if problems:
        print("Needs attention:")
        for r in problems:
            line = (f"  row {r['row']:>3}  {r['status']:<15} {ph(r['employee'])}"
                    f"  [{r['coaching_type']}]")
            # A note is free text, so ph() (which aliases a whole string as one name)
            # is wrong for it. Notes we generate are short technical strings ('ambiguous',
            # a selector timeout); on captured output, suppress any long enough to be a
            # stray clinical fragment — same rule as _echo().
            note = r["note"]
            if note:
                if phi_redact.console_redaction_on() and len(note) > 40:
                    note = f"[{len(note)} chars withheld]"
                line += f"  - {note}"
            print(line)
        print()
    print("Totals: " + "  ".join(f"{s}={n}" for s, n in sorted(tally.items())))


if __name__ == "__main__":
    if "--audit" in sys.argv:
        review_audit(last_run_only="--all" not in sys.argv)
    elif "--resume" in sys.argv:
        resume_batch()
    elif "--capture-fields" in sys.argv:
        i = sys.argv.index("--capture-fields")
        name = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        if not name:
            print('Usage: python ati_coaching_encounter.py --capture-fields "Last, First"')
        else:
            asyncio.run(run_capture_fields(name))
    elif "--capture-assessment" in sys.argv:
        i = sys.argv.index("--capture-assessment")
        name = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        # Optional 3rd arg: the tile label (default Physical Assessment). Only treat it
        # as a label if it isn't another flag.
        label = "Physical Assessment"
        if len(sys.argv) > i + 2 and not sys.argv[i + 2].startswith("--"):
            label = sys.argv[i + 2]
        if not name:
            print('Usage: python ati_coaching_encounter.py --capture-assessment '
                  '"Last, First" ["Tile Label"]')
        else:
            asyncio.run(run_capture_assessment(name, label))
    else:
        asyncio.run(run())
