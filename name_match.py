"""
name_match.py — matching a dictated name to the EMR's roster
============================================================
Dane says "Bill Thompson". The EMR says "Thompson, William". Both are correct; only
one of them is in the medical record.

This is the shared name-matching logic for both tools. It used to live inside
update_employees.py, where the encounters tool couldn't reach it — so the encounters
tool used a plain regex, which silently only worked for nicknames that happen to be a
PREFIX of the formal name ("Will" of "William"). "Bill", "Bob", "Peggy", "Chuck" and
"Dick" all failed, because they aren't prefixes of anything.

MATCHING IS DELIBERATELY CONSERVATIVE
    An ambiguous match is never guessed. If "Smith, Chris" could be Christopher Smith
    or Christina Smith, we return BOTH and let the caller refuse. Silently attaching a
    coaching encounter to the wrong employee's medical record is far worse than
    stopping to ask.
"""

import re

# ─────────────────────────────────────────────
# NORMALIZATION
# ─────────────────────────────────────────────

# Generational suffixes, stripped for loose matching (whole words, optional dot).
_SUFFIX_RE = re.compile(r"\b(?:jr|sr|ii|iii|iv|v)\b\.?", re.IGNORECASE)


def normalize_name(s):
    """Normalize a 'Last, First' name for matching: lowercase, collapse whitespace.

    The EMR roster sometimes has doubled spaces ('Doe,  Jane'), so runs of whitespace
    collapse and the space after the comma is normalized.
    """
    s = str(s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    return s


def loose_name(s):
    """Forgiving normalization: drops the EMR's quoted nicknames and suffixes.

    The EMR stores 'Skelton, Wilma "Sissy"', 'Rex, Thomas "Tom"', 'Larie Jr., William'.
    A plainly-dictated 'Skelton, Wilma' should still find her. Paired quotes only — a
    lone apostrophe (O'Brien) is left intact.
    """
    s = str(s or "")
    s = re.sub(r'"[^"]*"', " ", s)   # drop "Nick"
    s = re.sub(r"'[^']*'", " ", s)   # drop 'Nick' (needs a matching pair)
    s = _SUFFIX_RE.sub(" ", s)       # drop Jr/Sr/II/III/IV/V
    return normalize_name(s)


def split_last_first(display_name):
    """'Last, First Middle' -> (last, first_full). first_full keeps middle parts."""
    last, _, first_full = str(display_name or "").partition(",")
    return last.strip(), first_full.strip()


def quoted_nickname(display_name):
    """Pull the EMR's embedded nickname out of 'Poe, William "Will"' -> 'will'."""
    m = re.search(r'"([^"]+)"', str(display_name or ""))
    return m.group(1).strip().lower() if m else ""


# ─────────────────────────────────────────────
# NICKNAMES
# ─────────────────────────────────────────────
# Curated common-US-name map (formal -> nicknames). Also used by update_employees to
# flag roster entries that may need the EMR's  First "Nick"  treatment.

NICKNAMES = {
    "abigail": ["Abby"], "albert": ["Al", "Bert"], "alexander": ["Alex"],
    "alexandra": ["Alex", "Lexi"], "andrew": ["Andy", "Drew"], "angela": ["Angie"],
    "anthony": ["Tony"], "barbara": ["Barb"], "benjamin": ["Ben"], "bradley": ["Brad"],
    "bradford": ["Brad"], "brandon": ["Bran"], "catherine": ["Cathy", "Kate", "Katie"],
    "charles": ["Charlie", "Chuck"], "christina": ["Chris", "Tina"],
    "christine": ["Chris"], "christopher": ["Chris"], "cynthia": ["Cindy"],
    "daniel": ["Dan", "Danny"], "deborah": ["Deb", "Debbie"], "dennis": ["Denny"],
    "donald": ["Don", "Donnie"], "douglas": ["Doug"], "edward": ["Ed", "Eddie"],
    "elizabeth": ["Liz", "Beth", "Betty", "Lizzie"], "eugene": ["Gene"],
    "frances": ["Fran"], "francis": ["Frank"], "franklin": ["Frank"],
    "frederick": ["Fred"], "gerald": ["Jerry"], "gregory": ["Greg"],
    "harold": ["Harry"], "henry": ["Hank", "Harry"], "jacob": ["Jake"],
    "james": ["Jim", "Jimmy"], "jeffrey": ["Jeff"], "jennifer": ["Jen", "Jenny"],
    "jessica": ["Jess"], "jonathan": ["Jon"], "joseph": ["Joe", "Joey"],
    "joshua": ["Josh"], "katherine": ["Kate", "Katie", "Kathy"], "kathleen": ["Kathy"],
    "kenneth": ["Ken", "Kenny"], "kimberly": ["Kim"], "lawrence": ["Larry"],
    "leonard": ["Lenny", "Leo"], "margaret": ["Maggie", "Peggy", "Marge"],
    "matthew": ["Matt"], "megan": ["Meg"], "melissa": ["Mel"], "michael": ["Mike"],
    "michelle": ["Shelly"], "nathaniel": ["Nate"], "nicholas": ["Nick"],
    "pamela": ["Pam"], "patricia": ["Pat", "Patty", "Trish"], "patrick": ["Pat"],
    "peter": ["Pete"], "philip": ["Phil"], "phillip": ["Phil"], "rebecca": ["Becky"],
    "richard": ["Rick", "Rich", "Dick"], "robert": ["Rob", "Bob", "Bobby"],
    "ronald": ["Ron", "Ronnie"], "russell": ["Russ"], "samantha": ["Sam"],
    "samuel": ["Sam"], "sandra": ["Sandy"], "stephanie": ["Steph"],
    "stephen": ["Steve"], "steven": ["Steve"], "susan": ["Sue", "Susie"],
    "theodore": ["Ted", "Teddy"], "theresa": ["Terry"], "teresa": ["Terry"],
    "thomas": ["Tom", "Tommy"], "timothy": ["Tim"], "veronica": ["Ronnie"],
    "victoria": ["Vicky"], "vincent": ["Vince"], "walter": ["Walt"],
    "wesley": ["Wes"], "william": ["Bill", "Will", "Billy"], "zachary": ["Zach"],
}

# nickname -> {formal names it could stand for}. "Sam" -> {samantha, samuel}, which is
# precisely why an ambiguous hit must never be guessed.
NICK_TO_FORMAL = {}
for _formal, _nicks in NICKNAMES.items():
    for _n in _nicks:
        NICK_TO_FORMAL.setdefault(_n.lower(), set()).add(_formal)


def first_names_match(spoken, emr_first, emr_display=""):
    """Could `spoken` be the same first name as the EMR's `emr_first`?

    Accepts, in order: the same name; a shortening either way ("Will"/"William",
    minimum 3 characters so "Jo" doesn't match "Joseph"); a curated nickname in either
    direction ("Bill" -> William, or Dane says "William" where the EMR holds "Bill");
    and the EMR's own embedded nickname ('Poe, William "Will"' matches "Will").
    """
    a = str(spoken or "").strip().lower().split()
    b = str(emr_first or "").strip().lower().split()
    if not a or not b:
        return False
    a, b = a[0], b[0]  # given names only; middle names are noise here

    if a == b:
        return True

    # A shortening in either direction. 3+ chars: "Jo" must not match "Joseph".
    if len(a) >= 3 and b.startswith(a):
        return True
    if len(b) >= 3 and a.startswith(b):
        return True

    # Curated nicknames, both directions.
    if a in {n.lower() for n in NICKNAMES.get(b, [])}:
        return True
    if b in {n.lower() for n in NICKNAMES.get(a, [])}:
        return True

    # Both are nicknames of the same formal name ("Bill" / "Will" -> william).
    if NICK_TO_FORMAL.get(a, set()) & NICK_TO_FORMAL.get(b, set()):
        return True

    # The EMR's embedded nickname: 'Poe, William "Will"'.
    if a and a == quoted_nickname(emr_display):
        return True

    return False


def find_matches(spoken_name, candidates):
    """Match a dictated 'Last, First' against EMR display names.

    `candidates` is the EMR's roster text, in order. Returns (indices, how) where
    `indices` lists EVERY candidate that matched — more than one means ambiguous, and
    the caller must refuse rather than pick.

    Tiers, strongest first; the first tier that hits any candidate wins, so an exact
    match is never diluted by a fuzzy one elsewhere in the roster.
    """
    spoken_norm = normalize_name(spoken_name)
    spoken_loose = loose_name(spoken_name)
    s_last, s_first = split_last_first(spoken_name)
    s_last_n = normalize_name(s_last)

    exact, loose, nick = [], [], []

    for i, cand in enumerate(candidates):
        c_norm = normalize_name(cand)
        c_loose = loose_name(cand)
        c_last, c_first = split_last_first(cand)

        if spoken_norm and spoken_norm == c_norm:
            exact.append(i)
            continue
        if spoken_loose and spoken_loose == c_loose:
            loose.append(i)
            continue
        # Same surname + a first name that could be the same person.
        if s_last_n and normalize_name(loose_name(c_last)) == normalize_name(loose_name(s_last)):
            if first_names_match(s_first, c_first, cand):
                nick.append(i)

    for hits, how in ((exact, "exact"), (loose, "loose"), (nick, "nickname")):
        if hits:
            return hits, how
    return [], "none"
