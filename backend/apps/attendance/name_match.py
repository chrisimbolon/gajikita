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

G12f.2b (10 Nov): short pieces no longer count. "Hadi" was matched to "Prayuda Adi Susanto" because
"adi" sits inside "hadi"; now a contained part needs 4+ letters, the same-first-3-letters rule needs
words of 4+ letters, and the overall likeness is only used for words of 5+ letters.

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
    short, other = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 4 and short in other:                 # Tari / Mentari, Yuda / Prayuda, Syaifull / Syaiful
        return 0.9
    if len(a) >= 4 and len(b) >= 4 and a[:3] == b[:3]:     # Arif / Arief, Vincent / Vinsensius
        return 0.85
    if len(a) >= 4 and _subsequence(a, b):                 # Dila / Fadhilah
        return 0.8
    if min(len(a), len(b)) >= 5:                           # Supriyadi / Supriadi; never for short words
        return SequenceMatcher(None, a, b).ratio()
    return 0.0


def name_score(in_file, full_name):
    mine = [t for t in _tokens(in_file) if len(t) >= 3]
    theirs = _tokens(full_name)
    if not mine or not theirs:
        return None
    best = max(_pair(a, b) for a in mine for b in theirs)
    compact_mine, compact_theirs = "".join(mine), "".join(theirs)
    if compact_mine == compact_theirs:
        best = 1.0
    elif len(compact_mine) >= 3 and compact_theirs.startswith(compact_mine):   # EkoH / Eko Haryanto
        best = max(best, 0.95)
    return round(best, 3)


def names_match(in_file, full_name):
    score = name_score(in_file, full_name)
    return None if score is None else score >= MATCH


def distinct_names(names):
    """G12f.3.4: names in file order, each once (case and spacing ignored), blanks left out."""
    seen, out = set(), []
    for name in names:
        clean = " ".join((name or "").split())
        if clean and clean.casefold() not in seen:
            seen.add(clean.casefold())
            out.append(clean)
    return out


def check_names(names, full_name):
    """
    G12f.3.4 (11 Nov 2026): every name written for one ID, against the employee.
    -> ("bad" | "ok" | "none", [names that don't look like the employee]).

    One ID can carry two people when a combined file is read with a Department that no machine claims:
    the office's "Dila" (Staf, ID 2) landed on the plant's ID 2 together with "Feny". Checking only the
    first name ("Feny") said all was well; any name that does not match now makes the row red.
    """
    bad, ok = [], False
    for name in distinct_names(names):
        same = names_match(name, full_name)
        if same is False:
            bad.append(name)
        elif same:
            ok = True
    return ("bad" if bad else "ok" if ok else "none"), bad


def best_candidate(in_file, candidates):
    """candidates: [(key, full name)] -> (key, score) of the most similar name at or above MATCH, else None."""
    best = None
    for key, full_name in candidates:
        score = name_score(in_file, full_name)
        if score is not None and score >= MATCH and (best is None or score > best[1]):
            best = (key, score)
    return best


def suggest_pairs(wanted, candidates):
    """
    G12f.2b: who is each unknown machine name, decided for the whole file at once.

    wanted:     [(item, group, name in the file)]     group = the machine the ID belongs to
    candidates: {group: [(key, full name)]}           employees with no ID yet on that machine
    -> {item: (key, score)}. The best-scoring pairs are taken first; an employee is proposed at most
    once per machine and an item gets at most one. So "YUDA" (0.9) gets Prayuda before "Hadi" could,
    and a weaker look-alike never takes someone a stronger one needs.
    """
    scored = []
    for order, (item, group, name) in enumerate(wanted):
        for key, full_name in candidates.get(group, []):
            score = name_score(name, full_name)
            if score is not None and score >= MATCH:
                scored.append((-score, order, item, group, key))
    scored.sort(key=lambda x: (x[0], x[1]))
    out, used = {}, set()
    for neg, _, item, group, key in scored:
        if item in out or (group, key) in used:
            continue
        out[item] = (key, -neg)
        used.add((group, key))
    return out
