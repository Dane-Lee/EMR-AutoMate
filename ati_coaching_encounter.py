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
import os
from playwright.async_api import async_playwright, Page
from datetime import date, datetime

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

# Set to True (during testing) to save a screenshot + page HTML at each step into
# a ./debug folder. These captures let us fix selectors against the real EMR.
DEBUG_CAPTURE = True

BASE_URL = "https://aws.atiworksitesolutions.com"

# Persistent browser profile folder. Stores cookies + cache so the browser
# remembers your login AND your selected worksite (org) between runs — just like
# your normal Edge/Chrome does. Created automatically on first run.
USER_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".browser_profile")

# Batch input file. If this CSV exists next to the script, you'll be offered batch
# mode: it reads each row, fills the form, and pauses for your review per encounter.
# An AI (Claude/ChatGPT) transcribes your dictated notes into this file — see
# TRANSCRIPTION_PROMPT.md for the exact column/value spec.
ENCOUNTERS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "encounters.csv")

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

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

async def snap(page: Page, label: str):
    """Save a screenshot + the page's HTML to ./debug for selector debugging.

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
        await page.screenshot(path=base + ".png", full_page=True)
        html = await page.content()
        with open(base + ".html", "w", encoding="utf-8") as fh:
            fh.write(html)
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
    print(f"  Employee:       {employee}")
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
        print(f"  Description:    {description}")
    print(f"  Prompted by:    {what_prompted}")
    print("──────────────────────────────────────────")

    again = input("\nLook right? ENTER to launch, or type 'r' to re-enter: ").strip().lower()
    if again == "r":
        return prompt_encounter()
    return encounter


# ─────────────────────────────────────────────
# MAIN FLOW
# ─────────────────────────────────────────────

async def fill_encounter(page: Page, ENCOUNTER):
    """Fill and save a single coaching encounter (assumes already logged in)."""
    # ── BACK TO DASHBOARD ──────────────────────
    # Reset to the home screen so the employee search box is available.
    await page.goto(BASE_URL)
    await page.wait_for_load_state("networkidle")
    await snap(page, "01_dashboard")

    # ── FIND EMPLOYEE ──────────────────────────
    # The dashboard preloads the FULL roster into .employee-list, so we locate the
    # person directly by name. The search box is only a client-side filter and its
    # matching doesn't handle the "Last, First" format, so we don't rely on it —
    # it's just a fallback to narrow the list if the direct match isn't found.
    full_name = ENCOUNTER["employee_search"].strip()
    print(f"Locating employee: {full_name}")

    rows = page.locator(".employee-list .details", has_text=full_name)
    if await rows.count() == 0:
        last_name = full_name.split(",")[0].strip()
        print(f"  Not found directly — narrowing the list by '{last_name}'...")
        box = page.locator("input[placeholder='Search Employee or Identifier']")
        await box.click()
        await box.fill(last_name)
        await page.wait_for_timeout(1200)
        rows = page.locator(".employee-list .details", has_text=full_name)

    await snap(page, "02_employee_list")

    if await rows.count() == 0:
        raise RuntimeError(
            f"Couldn't find employee '{full_name}'. Check spelling and the "
            f"'Last, First' format, and that they exist in this worksite."
        )

    target = rows.first
    await target.scroll_into_view_if_needed()
    await target.click()
    await page.wait_for_load_state("networkidle")
    # The Employee Overview keeps loading (cases / follow-ups / portfolio) after
    # networkidle and re-renders, so let it settle before clicking Add Case.
    await page.wait_for_timeout(2500)
    print("Employee selected.")
    await snap(page, "03_employee_selected")

    # ── ADD CASE ───────────────────────────────
    add_case_btn = page.locator("button:has-text('+ Add Case')")
    await add_case_btn.wait_for(state="visible", timeout=20000)
    try:
        await add_case_btn.click(timeout=8000)
    except Exception:
        # If a late re-render keeps intercepting the click, force it.
        print("  Add Case retry (force-click)...")
        await add_case_btn.click(force=True)
    await page.wait_for_timeout(800)
    await snap(page, "04_add_case_modal")

    # In the "Select Assessment Type" modal, click the Coaching Encounter tile.
    # Each option is a `.assessment-type-container` div — click the container so the
    # selection registers (clicking just the text doesn't always trigger it).
    tile = page.locator(".assessment-type-container", has_text="Coaching Encounter")
    await tile.click()
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
        errs.append(f"Row {line_no}: encounter_type '{encounter_type}' is not valid. "
                    f"Use one of: {' | '.join(ENCOUNTER_TYPES)}")

    coaching_type = get("coaching_type")
    if coaching_type not in COACHING_TYPE_UUIDS:
        errs.append(f"Row {line_no}: coaching_type '{coaching_type}' is not valid. "
                    f"Use one of: {' | '.join(COACHING_TYPE_UUIDS)}")

    detail_set = CHECKBOX_UUID_MAP.get(coaching_type, {})
    details = [d.strip() for d in get("details").split(";") if d.strip()]
    for d in details:
        if d not in detail_set:
            valid = ", ".join(detail_set) if detail_set else "(this type has no detail options)"
            errs.append(f"Row {line_no}: detail '{d}' is not valid for "
                        f"{coaching_type or '(no type)'}. Valid: {valid}")

    what_prompted = get("what_prompted") or WHAT_PROMPTED_OPTIONS[0]
    if what_prompted not in WHAT_PROMPTED_OPTIONS:
        errs.append(f"Row {line_no}: what_prompted '{what_prompted}' is not valid. "
                    f"Use one of: {' | '.join(WHAT_PROMPTED_OPTIONS)}")

    encounter = {
        "employee_search": employee,
        "date_of_encounter": date_val,
        "encounter_type": encounter_type,
        "department": get("department") or None,
        "division": get("division") or None,
        "category": get("category") or None,
        "shift": get("shift") or None,
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
        print(f"  {i}. {enc['employee_search']}  |  {enc['coaching_type'] or '(no type)'}"
              f"  |  {enc['date_of_encounter']}  |  {det}")

    if errors:
        print("\n⚠ Fix these problems in encounters.csv before entering:")
        for e in errors:
            print(f"   - {e}")
        print("\nNothing was entered. Correct the CSV and run again.")
        raise SystemExit(1)

    if not popup(f"Found {len(encounters)} encounter(s) in encounters.csv.\n\n"
                 "Enter them into the EMR now?", yes_no=True):
        print("Okay — manual entry instead.")
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
    print(f"Entering {len(encounters)} encounter(s) from encounters.csv.")
    for i, encounter in enumerate(encounters, 1):
        print(f"\n══ Encounter {i} of {len(encounters)}: "
              f"{encounter['employee_search']} ══")
        try:
            status = await fill_encounter(page, encounter)
        except Exception as e:
            print(f"\n⚠ Error on this encounter: {e}")
            await snap(page, "ERROR_state")
            print("  (Screenshot + page HTML saved to ./debug.)")
            if not popup("That encounter hit an error and was skipped.\n\n"
                         "Continue with the next one?", yes_no=True):
                break
            continue
        if status == "quit":
            print("Stopping the batch here.")
            break
    print("\nBatch complete.")


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


if __name__ == "__main__":
    asyncio.run(run())
