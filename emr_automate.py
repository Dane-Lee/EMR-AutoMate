"""
EMR AutoMate — launcher
=======================
Single entry point for the EMR AutoMate functions. On start it shows an on-top
dialog with labeled buttons, then hands off to that flow:

    Coaching Encounters → ati_coaching_encounter.run
    Update Roster        → update_employees.run
    Cancel               → quit

USAGE
    python emr_automate.py
"""

import asyncio

import ati_coaching_encounter
import update_employees


def popup_choice():
    """Show a labeled-button chooser. Returns 'encounters', 'roster', or 'cancel'.

    Uses the native Windows Task Dialog (comctl32) with real command-link buttons —
    reliable where tkinter wasn't. Falls back to a MessageBoxW Yes/No/Cancel, then to
    a terminal prompt.
    """
    import ctypes
    from ctypes import wintypes

    ENCOUNTERS_ID, ROSTER_ID = 101, 102
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

        buttons = (TASKDIALOG_BUTTON * 2)(
            (ENCOUNTERS_ID, "Coaching Encounters"),
            (ROSTER_ID, "Update Roster"),
        )
        cfg = TASKDIALOGCONFIG()
        cfg.cbSize = ctypes.sizeof(TASKDIALOGCONFIG)
        cfg.dwFlags = TDF_USE_COMMAND_LINKS | TDF_POSITION_RELATIVE_TO_WINDOW
        cfg.dwCommonButtons = TDCBF_CANCEL_BUTTON
        cfg.pszWindowTitle = "EMR AutoMate"
        cfg.pszMainInstruction = "What do you want to do?"
        cfg.pszContent = "Choose a task to run."
        cfg.cButtons = 2
        cfg.pButtons = ctypes.cast(buttons, ctypes.c_void_p)
        cfg.nDefaultButton = ENCOUNTERS_ID

        pressed = ctypes.c_int()
        hr = ctypes.windll.comctl32.TaskDialogIndirect(
            ctypes.byref(cfg), ctypes.byref(pressed), None, None)
        if hr != 0:
            raise OSError(f"TaskDialogIndirect hr={hr}")
        return {ENCOUNTERS_ID: "encounters", ROSTER_ID: "roster"}.get(
            pressed.value, "cancel")
    except Exception:
        try:
            style = 0x03 | 0x20 | 0x00010000 | 0x00040000  # YESNOCANCEL|?|SETFG|TOPMOST
            r = ctypes.windll.user32.MessageBoxW(
                0,
                "Pick a task:\n\n"
                "     Yes  =  Coaching Encounters\n"
                "     No   =  Update Roster\n"
                "     Cancel = quit",
                "EMR AutoMate", style)
            return {6: "encounters", 7: "roster"}.get(r, "cancel")
        except Exception:
            ans = input("[e]ncounters / [r]oster / [q]uit: ").strip().lower()
            return {"e": "encounters", "r": "roster"}.get(ans[:1], "cancel")


def main():
    choice = popup_choice()
    if choice == "encounters":
        print("→ Coaching encounters")
        asyncio.run(ati_coaching_encounter.run())
    elif choice == "roster":
        print("→ Update employee roster")
        asyncio.run(update_employees.run())
    else:
        print("Cancelled. Goodbye.")


if __name__ == "__main__":
    main()
