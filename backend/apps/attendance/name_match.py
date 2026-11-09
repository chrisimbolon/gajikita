# =============================================================================
# === backend/apps/attendance/name_match.py ===
# =============================================================================
"""
Does the name written in the machine look like the employee's name? (G12f.2, 9 Nov 2026). Pure.

Machines hold short names and nicknames: "GANDA" (Ganda Bintan Prasongko), "Arif" (Arief
Chaniago), "Ridwan" (Riduan H.S), "Yuda" (Prayuda), "Tari" (Mentari), "Dila" (Apriyani
Fadhilah), "Vincent" (Vinsensius). Those must count as the same person. "Feny" against
"Apriyani Fadhilah" must not: that is the plant's ID 2 read on the office machine, the mistake
this check exists to catch.

name_score(in_file, full_name) -> 0..1, or None when the file has no usable name (.dat, CSV).
names_match(...)               -> True / False / None (None = nothing to compare).
"""
import re
from difflib import SequenceMatcher

MATCH = 0.75                       # at or above: the same person as far as the names can tell


def _tokens(text):
    return re.findall(r"[a-z]+", str(text or "").casefold())


def _subsequence(short, long):
    """'dila' in 'fadhilah': every letter of short appears in long, in order."""
    it = iter(long)
    return all(ch in it for ch in short)


def _pair(a, b):
    if a == b:
        return 1.0
    if len(b) >= 3 and (a in b or b in a):                 # Tari / Mentari, Syaifull / Syaiful
        return 0.9
    if a[:3] == b[:3]:                                     # Arif / Arief, Vincent / Vinsensius
        return 0.85
    if len(a) >= 4 and _subsequence(a, b):                 # Dila / Fadhilah
        return 0.8
    return SequenceMatcher(None, a, b).ratio()


def name_score(in_file, full_name):
    mine = [t for t in _tokens(in_file) if len(t) >= 3]
    theirs = _tokens(full_name)
    if not mine or not theirs:
        return None
    best = max(_pair(a, b) for a in mine for b in theirs)
    compact_mine, compact_theirs = "".join(mine), "".join(theirs)
    if compact_mine == compact_theirs:
        best = 1.0
    elif len(compact_mine) >= 3 and compact_mine in compact_theirs:   # EkoH / Eko Haryanto
        best = max(best, 0.95)
    return round(best, 3)


def names_match(in_file, full_name):
    score = name_score(in_file, full_name)
    return None if score is None else score >= MATCH


def best_candidate(in_file, candidates):
    """candidates: [(key, full name)] -> (key, score) of the most similar name at or above MATCH, else None."""
    best = None
    for key, full_name in candidates:
        score = name_score(in_file, full_name)
        if score is not None and score >= MATCH and (best is None or score > best[1]):
            best = (key, score)
    return best
