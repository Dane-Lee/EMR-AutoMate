"""
EMR AutoMate — launcher
=======================
Single entry point for the EMR AutoMate functions. On start it shows an on-top
dialog with labeled buttons, then hands off to that flow:

    Build a Batch        → encounter_builder (check names off the roster)
    Enter the Batch      → ati_coaching_encounter.run
    Update Roster        → update_employees.run
    Cancel               → quit

USAGE
    python emr_automate.py
"""

import asyncio

import ati_coaching_encounter
import update_employees


def popup_choice():
    """Show a labeled-button chooser. Returns 'build', 'encounters', 'roster', or
    'cancel'.

    Uses the native Windows Task Dialog (comctl32) with real command-link buttons —
    reliable where tkinter wasn't. Falls back to a MessageBoxW Yes/No/Cancel, then to
    a terminal prompt.
    """
    import ctypes
    from ctypes import wintypes

    BUILD_ID, ENCOUNTERS_ID, ROSTER_ID = 100, 101, 102
    try:
        class TASKDIALOG_BUTTON(ctypes.Structure):
            _pack_ = 1
            _fields_ = [("nButtonID", ctypes.c_int),
                        ("pszButtonText", ctypes.c_wchar_p)]

        class TASKDIALOGCONFIG(ctypes.Structure):
            _pack_ = 1
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("hwndParent", wintypes.HWND),
                ("hInstance", wintypes.HINSTANCE),
                ("dwFlags", ctypes.c_int),
                ("dwCommonButtons", ctypes.c_int),
                ("pszWindowTitle", ctypes.c_wchar_p),
                ("pszMainIcon", ctypes.c_wchar_p),
                ("pszMainInstruction", ctypes.c_wchar_p),
                ("pszContent", ctypes.c_wchar_p),
                ("cButtons", ctypes.c_uint),
                ("pButtons", ctypes.c_void_p),
                ("nDefaultButton", ctypes.c_int),
                ("cRadioButtons", ctypes.c_uint),
                ("pRadioButtons", ctypes.c_void_p),
                ("nDefaultRadioButton", ctypes.c_int),
                ("pszVerificationText", ctypes.c_wchar_p),
                ("pszExpandedInformation", ctypes.c_wchar_p),
                ("pszExpandedControlText", ctypes.c_wchar_p),
                ("pszCollapsedControlText", ctypes.c_wchar_p),
                ("pszFooterIcon", ctypes.c_wchar_p),
                ("pszFooter", ctypes.c_wchar_p),
                ("pfCallback", ctypes.c_void_p),
                ("lpCallbackData", ctypes.c_void_p),
                ("cxWidth", ctypes.c_uint),
            ]

        TDF_USE_COMMAND_LINKS = 0x0010
        TDF_POSITION_RELATIVE_TO_WINDOW = 0x1000
        TDCBF_CANCEL_BUTTON = 0x0008

        buttons = (TASKDIALOG_BUTTON * 3)(
            (BUILD_ID, "Build a Batch\nCheck names off the roster to make encounters.csv"),
            (ENCOUNTERS_ID, "Enter the Batch\nDrive the EMR and save encounters.csv as drafts"),
            (ROSTER_ID, "Update Roster\nPush roster.xlsx changes into the EMR"),
        )
        cfg = TASKDIALOGCONFIG()
        cfg.cbSize = ctypes.sizeof(TASKDIALOGCONFIG)
        cfg.dwFlags = TDF_USE_COMMAND_LINKS | TDF_POSITION_RELATIVE_TO_WINDOW
        cfg.dwCommonButtons = TDCBF_CANCEL_BUTTON
        cfg.pszWindowTitle = "EMR AutoMate"
        cfg.pszMainInstruction = "What do you want to do?"
        cfg.pszContent = "Build a batch first, then enter it."
        cfg.cButtons = 3
        cfg.pButtons = ctypes.cast(buttons, ctypes.c_void_p)
        cfg.nDefaultButton = BUILD_ID

        pressed = ctypes.c_int()
        hr = ctypes.windll.comctl32.TaskDialogIndirect(
            ctypes.byref(cfg), ctypes.byref(pressed), None, None)
        if hr != 0:
            raise OSError(f"TaskDialogIndirect hr={hr}")
        return {BUILD_ID: "build", ENCOUNTERS_ID: "encounters",
                ROSTER_ID: "roster"}.get(pressed.value, "cancel")
    except Exception:
        try:
            style = 0x03 | 0x20 | 0x00010000 | 0x00040000  # YESNOCANCEL|?|SETFG|TOPMOST
            r = ctypes.windll.user32.MessageBoxW(
                0,
                "Pick a task:\n\n"
                "     Yes  =  Build a Batch\n"
                "     No   =  Enter the Batch\n"
                "     Cancel = quit\n\n"
                "(Update Roster: run  python update_employees.py)",
                "EMR AutoMate", style)
            return {6: "build", 7: "encounters"}.get(r, "cancel")
        except Exception:
            ans = input("[b]uild / [e]nter / [r]oster / [q]uit: ").strip().lower()
            return {"b": "build", "e": "encounters",
                    "r": "roster"}.get(ans[:1], "cancel")


def main():
    choice = popup_choice()
    if choice == "build":
        print("→ Build a batch")
        # Imported here, not at module scope: it builds a tkinter window, and the
        # other two flows have no business paying for that.
        import encounter_builder
        encounter_builder.main()
    elif choice == "encounters":
        print("→ Enter the batch")
        asyncio.run(ati_coaching_encounter.run())
    elif choice == "roster":
        print("→ Update employee roster")
        asyncio.run(update_employees.run())
    else:
        print("Cancelled. Goodbye.")


if __name__ == "__main__":
    main()
