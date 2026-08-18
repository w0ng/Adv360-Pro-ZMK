#!/usr/bin/env python3
"""
Replay a recorded keystroke stream through a simulation of ZMK's hold-tap
state machine, and report how often home row mods would misfire.

Implements the semantics documented at
https://zmk.dev/docs/keymaps/behaviors/hold-tap :

  balanced flavor          hold triggers when tapping-term-ms expires, or when
                           another key is pressed AND released while held
  require-prior-idle-ms    press within this window of the previous non-modifier
                           keypress always resolves as a tap
  quick-tap-ms             re-press of the same hold-tap within this window of
                           its previous press always resolves as a tap
  hold-trigger-key-positions   a key outside the list forces a tap
  hold-trigger-on-release  that positional check runs on the other key's RELEASE
                           rather than its press

Usage:  ./analyze.py typing-2026-08-19.json
"""
from __future__ import annotations

import argparse
import json
import sys

if sys.version_info < (3, 7):
    sys.exit(
        "analyze.py needs Python 3.7 or newer (found %d.%d).\n"
        "See README.md > Requirements for install instructions."
        % (sys.version_info[0], sys.version_info[1]))
from dataclasses import dataclass, replace

# --- physical key -> hand ---------------------------------------------------

_LEFT = """Backquote Digit1 Digit2 Digit3 Digit4 Digit5 Tab KeyQ KeyW KeyE KeyR
KeyT CapsLock KeyA KeyS KeyD KeyF KeyG ShiftLeft KeyZ KeyX KeyC KeyV KeyB
ControlLeft AltLeft MetaLeft Escape""".split()

_RIGHT = """Digit6 Digit7 Digit8 Digit9 Digit0 Minus Equal Backspace KeyY KeyU
KeyI KeyO KeyP BracketLeft BracketRight Backslash KeyH KeyJ KeyK KeyL Semicolon
Quote Enter KeyN KeyM Comma Period Slash ShiftRight ControlRight AltRight
MetaRight""".split()

HAND = {c: "L" for c in _LEFT}
HAND.update({c: "R" for c in _RIGHT})
HAND["Space"] = "T"  # thumb: counts as opposite-hand for both sides

# QWERTY finger columns. Two keys on the same finger cannot be chorded at all.
_COLS = [
    ("L pinky",  "Backquote Digit1 KeyQ KeyA KeyZ Tab CapsLock ShiftLeft Escape"),
    ("L ring",   "Digit2 KeyW KeyS KeyX"),
    ("L middle", "Digit3 KeyE KeyD KeyC"),
    ("L index",  "Digit4 Digit5 KeyR KeyT KeyF KeyG KeyV KeyB"),
    ("R index",  "Digit6 Digit7 KeyY KeyU KeyH KeyJ KeyN KeyM"),
    ("R middle", "Digit8 KeyI KeyK Comma"),
    ("R ring",   "Digit9 KeyO KeyL Period"),
    ("R pinky",  "Digit0 Minus Equal KeyP BracketLeft BracketRight Backslash "
                 "Semicolon Quote Slash Enter Backspace ShiftRight"),
    ("thumb",    "Space"),
]
FINGER = {c: name for name, keys in _COLS for c in keys.split()}
FINGER_ORDER = [name for name, _ in _COLS]

DEFAULT_HRM = ["KeyA", "KeyS", "KeyD", "KeyF", "KeyJ", "KeyK", "KeyL", "Semicolon"]
BOTTOM_HRM = ["KeyZ", "KeyX", "KeyC", "KeyV", "KeyM", "Comma", "Period", "Slash"]
ROWS = {"home": DEFAULT_HRM, "bottom": BOTTOM_HRM}

# which keys a given chord drill is exercising
CHORD_KEYS = {"chords": DEFAULT_HRM, "chords_bot": BOTTOM_HRM}

# ZMK: require-prior-idle-ms measures from "another non-modifier key". A Shift
# press does NOT reset the window. This matters a lot for code, where shifted
# symbols are everywhere. Modifiers still count as interrupts for the balanced
# flavor -- only the idle timer ignores them.
MODIFIERS = {"ShiftLeft", "ShiftRight", "ControlLeft", "ControlRight",
             "AltLeft", "AltRight", "MetaLeft", "MetaRight"}

_GLYPH = {"Semicolon": ";", "Quote": "'", "Comma": ",", "Period": ".",
          "Slash": "/", "Minus": "-", "Equal": "=", "Backquote": "`",
          "BracketLeft": "[", "BracketRight": "]", "Backslash": "\\",
          "Space": "␣", "Enter": "⏎", "Backspace": "⌫", "Tab": "⇥",
          "ShiftLeft": "⇧", "ShiftRight": "⇧", "ControlLeft": "⌃",
          "ControlRight": "⌃", "AltLeft": "⌥", "AltRight": "⌥",
          "MetaLeft": "⌘", "MetaRight": "⌘", "CapsLock": "⇪", "Escape": "⎋"}


def glyph(code: str) -> str:
    if code in _GLYPH:
        return _GLYPH[code]
    if code.startswith("Key"):
        return code[3:].lower()
    if code.startswith("Digit"):
        return code[5:]
    return code


# --- model ------------------------------------------------------------------

@dataclass(frozen=True)
class Params:
    tapping_term: float = 280.0
    quick_tap: float = 175.0
    prior_idle: float = 150.0
    hold_trigger_on_release: bool = True
    positional: bool = True          # hold-trigger-key-positions = opposite hand


@dataclass
class Press:
    code: str
    down: float
    up: float

    @property
    def hand(self) -> str:
        return HAND.get(self.code, "?")

    @property
    def dur(self) -> float:
        return self.up - self.down


def pair_events(events: list[dict]) -> list[Press]:
    """Match each keydown with its keyup. Unmatched downs are dropped."""
    events = sorted(events, key=lambda e: (e["t"], e["d"]))
    open_: dict[str, list[float]] = {}
    out: list[Press] = []
    for e in events:
        if e["d"]:
            open_.setdefault(e["c"], []).append(e["t"])
        else:
            q = open_.get(e["c"])
            if q:
                out.append(Press(e["c"], q.pop(0), e["t"]))
    out.sort(key=lambda p: p.down)
    return out


def resolve(idx: int, presses: list[Press], prm: Params,
            hrm: set[str], last_press_t: float | None,
            last_same_t: float | None) -> tuple[str, str, str, Press | None]:
    """Resolve one hold-tap press.

    Returns (tap|hold, reason, category, interrupting press or None), category
    prior-idle | quick-tap | same | cross | own-release | timeout.
    """
    p = presses[idx]
    t0 = p.down

    if last_press_t is not None and (t0 - last_press_t) < prm.prior_idle:
        return "tap", "require-prior-idle", "prior-idle", None
    if last_same_t is not None and (t0 - last_same_t) < prm.quick_tap:
        return "tap", "quick-tap", "quick-tap", None

    deadline = t0 + prm.tapping_term
    horizon = min(p.up, deadline)

    evs: list[tuple[float, str, Press]] = []
    for q in presses[idx + 1:]:
        if q.down > horizon:
            break
        evs.append((q.down, "down", q))
        if q.up <= horizon:
            evs.append((q.up, "up", q))
    evs.sort(key=lambda x: (x[0], 0 if x[1] == "up" else 1))

    for _t, kind, q in evs:
        cross = (q.hand != p.hand) or q.hand == "T"
        side = "cross" if cross else "same"
        allowed = cross if prm.positional else True
        if prm.hold_trigger_on_release:
            if kind == "up":
                if allowed:
                    return ("hold",
                            f"balanced interrupt ({glyph(q.code)}, {side}-hand)",
                            side, q)
                return "tap", f"positional ({glyph(q.code)}, same-hand)", "same", q
        else:
            if kind == "down" and not allowed:
                return "tap", f"positional ({glyph(q.code)}, same-hand)", "same", q
            if kind == "up" and allowed:
                return ("hold",
                        f"balanced interrupt ({glyph(q.code)}, {side}-hand)", side, q)

    if p.up < deadline:
        return "tap", "released before tapping-term", "own-release", None
    return "hold", "tapping-term expired", "timeout", None


WORD_BREAK = {"Space", "Enter", "Tab", "Backspace"}


def word_at(presses: list[Press], i: int, cap: int = 24) -> str:
    """The word being typed when presses[i] happened, with [key] marked."""
    lo = i
    while lo > 0 and presses[lo - 1].code not in WORD_BREAK and i - lo < cap:
        lo -= 1
    hi = i
    while hi + 1 < len(presses) and presses[hi + 1].code not in WORD_BREAK \
            and hi - i < cap:
        hi += 1
    out = []
    for k in range(lo, hi + 1):
        if k != i and presses[k].code in MODIFIERS:
            continue                      # Shift etc. would clutter the word
        g = glyph(presses[k].code)
        out.append(f"[{g}]" if k == i else g)
    return "".join(out)


def simulate(sessions: list[tuple[str, list[Press]]], prm: Params,
             hrm: set[str]) -> dict:
    """Every HRM press in normal typing is INTENDED as a letter.

    Sessions are simulated independently. Browser event timestamps restart at
    zero on every page load, so concatenating sessions would fabricate
    adjacencies across the boundary and corrupt the counts.
    """
    total = holds = deferred = 0
    misfires: list[tuple[str, Press, str, str]] = []
    cause = {"cross": 0, "same": 0, "timeout": 0}
    per: dict[str, dict] = {}
    by_key: dict[str, dict] = {}
    bigrams: dict[str, int] = {}
    trigrams: dict[str, int] = {}
    words: dict[str, int] = {}

    for mode, raw in sessions:
        presses = sorted(raw, key=lambda p: p.down)
        pm = per.setdefault(mode, {"presses": 0, "misfires": 0, "deferred": 0,
                                   "keys": len(presses)})
        last_press_t: float | None = None
        last_same: dict[str, float] = {}
        for i, p in enumerate(presses):
            if p.code in hrm:
                total += 1
                pm["presses"] += 1
                bk = by_key.setdefault(p.code, {"presses": 0, "misfires": 0})
                bk["presses"] += 1
                verdict, why, cat, other = resolve(i, presses, prm, hrm,
                                                   last_press_t,
                                                   last_same.get(p.code))
                if verdict == "hold":
                    holds += 1
                    pm["misfires"] += 1
                    bk["misfires"] += 1
                    cause[cat] = cause.get(cat, 0) + 1
                    prev = presses[i - 1] if i else None
                    nxt = presses[i + 1] if i + 1 < len(presses) else None
                    ctx = (glyph(prev.code) if prev else "·") + "[" + glyph(p.code) \
                        + "]" + (glyph(nxt.code) if nxt else "·")
                    misfires.append((mode, p, ctx, why))
                    bg = glyph(p.code) + (glyph(other.code) if other else "·")
                    bigrams[bg] = bigrams.get(bg, 0) + 1
                    trigrams[ctx] = trigrams.get(ctx, 0) + 1
                    w = word_at(presses, i)
                    words[w] = words.get(w, 0) + 1
                elif why not in ("require-prior-idle", "quick-tap"):
                    deferred += 1
                    pm["deferred"] += 1
                last_same[p.code] = p.down
            if p.code not in MODIFIERS:
                last_press_t = p.down

    return {"total": total, "misfires": holds, "deferred": deferred,
            "examples": misfires, "cause": cause, "per": per, "by_key": by_key,
            "bigrams": bigrams, "trigrams": trigrams, "words": words}


def simulate_chords(sessions: list[tuple[str, list[Press]]], prm: Params,
                    hrm: set[str]) -> dict:
    """Overlapped HRM presses in a chord drill are INTENDED as holds."""
    out: dict = {"cross": [0, 0], "same": [0, 0]}
    fails: list[tuple[str, Press, Press, str]] = []
    per: dict[str, dict] = {}
    by_key: dict[str, dict] = {}
    bigrams: dict[str, int] = {}

    for mode, raw in sessions:
        presses = sorted(raw, key=lambda p: p.down)
        pm = per.setdefault(mode, {"attempts": 0, "failed": 0})
        cbg = bigrams
        last_press_t: float | None = None
        last_same: dict[str, float] = {}
        for i, p in enumerate(presses):
            nxt = presses[i + 1] if i + 1 < len(presses) else None
            if p.code in hrm and nxt is not None and nxt.down < p.up:
                cross = (nxt.hand != p.hand) or nxt.hand == "T"
                bucket = "cross" if cross else "same"
                out[bucket][0] += 1
                pm["attempts"] += 1
                bk = by_key.setdefault(p.code, {"attempts": 0, "failed": 0,
                                                "cross": 0, "same": 0})
                bk["attempts"] += 1
                bk[bucket] += 1
                verdict, why, _cat, _o = resolve(i, presses, prm, hrm,
                                                 last_press_t,
                                                 last_same.get(p.code))
                if verdict == "tap":
                    out[bucket][1] += 1
                    pm["failed"] += 1
                    bk["failed"] += 1
                    fails.append((mode, p, nxt, why))
                    bg = glyph(p.code) + glyph(nxt.code)
                    cbg[bg] = cbg.get(bg, 0) + 1
            if p.code in hrm:
                last_same[p.code] = p.down
            if p.code not in MODIFIERS:
                last_press_t = p.down

    out["examples"] = fails
    out["per"] = per
    out["by_key"] = by_key
    out["bigrams"] = bigrams
    out["total"] = out["cross"][0] + out["same"][0]
    out["failed"] = out["cross"][1] + out["same"][1]
    return out


MODE_LABELS = {"words": "Common words", "words_bot": "Bottom-row words",
               "code": "Code (TSX)", "free": "Free typing", "prose": "Prose (old)",
               "chords": "Chords: home row", "chords_bot": "Chords: bottom row"}

IDLE_MS = 3000.0   # a gap longer than this is a pause, not typing


def mode_stats(sessions: list[list[Press]]) -> dict:
    """Speed and roll behaviour, accumulated over sessions kept separate."""
    ikis: list[float] = []
    active = span = 0.0
    over = inv = pairs = n = 0
    for raw in sessions:
        ps = sorted(raw, key=lambda p: p.down)
        n += len(ps)
        if len(ps) > 1:
            span += (ps[-1].down - ps[0].down) / 1000
        for i in range(1, len(ps)):
            a, b = ps[i - 1], ps[i]
            gap = b.down - a.down
            if 0 <= gap < IDLE_MS:
                ikis.append(gap)
                active += gap / 1000
            pairs += 1
            if b.down < a.up:
                over += 1
                if b.up < a.up:
                    inv += 1
    return {"keys": n,
            "wpm": (n / 5) / (active / 60) if active > 5 else 0.0,
            "raw": (n / 5) / (span / 60) if span > 5 else 0.0,
            "gap": pct(ikis, .5) if ikis else 0.0,
            "over": 100 * over / pairs if pairs else 0.0,
            "inv": 100 * inv / pairs if pairs else 0.0,
            "mins": span / 60}


def print_by_tab(typing, chords, W) -> None:
    groups: dict[str, list[list[Press]]] = {}
    for m, ps in typing:
        groups.setdefault(m, []).append(ps)
    order = [k for k in MODE_LABELS if k in groups] + \
            [k for k in groups if k not in MODE_LABELS]

    print("=" * W)
    print("  SPEED BY TAB")
    print("=" * W)
    print(f"  {'tab':<20}{'keys':>7}{'wpm':>6}{'raw':>6}{'gap':>6}"
          f"{'overlap':>10}{'out-of-order':>14}")
    for m in order:
        s = mode_stats(groups[m])
        print(f"  {MODE_LABELS.get(m, m):<20}{s['keys']:>7,}{s['wpm']:>6.0f}"
              f"{s['raw']:>6.0f}{s['gap']:>5.0f}ms{s['over']:>9.1f}%{s['inv']:>13.2f}%")
    s = mode_stats([ps for sess in groups.values() for ps in sess])
    print(f"  {'-' * 67}")
    print(f"  {'all typing':<20}{s['keys']:>7,}{s['wpm']:>6.0f}"
          f"{s['raw']:>6.0f}{s['gap']:>5.0f}ms{s['over']:>9.1f}%{s['inv']:>13.2f}%")
    print()
    print("  wpm  active typing only, gaps over 3 s excluded")
    print("  raw  wall clock, thinking pauses included")
    print("  out-of-order  you released the previous key AFTER the next one —")
    print("                the raw physical ceiling on how often a mod can misfire")
    if chords:
        cg: dict[str, list[list[Press]]] = {}
        for m, ps in chords:
            cg.setdefault(m, []).append(ps)
        print()
        print("  chord drills, shown separately — deliberately overlapping, so their")
        print("  out-of-order rate is by design and must not be averaged in:")
        for m, ps in cg.items():
            s = mode_stats(ps)
            print(f"  {MODE_LABELS.get(m, m):<20}{s['keys']:>7,}{'':>12}"
                  f"{s['gap']:>5.0f}ms{s['over']:>9.1f}%{s['inv']:>13.2f}%")
    print()


# --- stats ------------------------------------------------------------------

def pct(vals: list[float], q: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    k = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[k]


def profile(sessions: list[tuple[str, list[Press]]], hrm: set[str]) -> dict:
    ikis: list[float] = []
    durs: list[float] = []
    pairs = overlap = inversion = 0
    keys = 0
    span = 0.0
    inv_bigrams: dict[str, int] = {}

    for _mode, ps in sessions:
        keys += len(ps)
        if len(ps) > 1:
            span += (ps[-1].down - ps[0].down) / 1000.0
        for p in ps:
            if 0 <= p.dur < 1000:
                durs.append(p.dur)
        for i in range(1, len(ps)):
            a, b = ps[i - 1], ps[i]
            gap = b.down - a.down
            if 0 <= gap < 2000:
                ikis.append(gap)
            pairs += 1
            if b.down < a.up:
                overlap += 1
                if b.up < a.up:
                    inversion += 1
                    if a.code in hrm:
                        k = glyph(a.code) + glyph(b.code)
                        inv_bigrams[k] = inv_bigrams.get(k, 0) + 1

    return {"keys": keys, "span": span, "ikis": ikis, "durs": durs,
            "pairs": pairs, "overlap": overlap, "inversion": inversion,
            "inv_bigrams": inv_bigrams}


# --- report -----------------------------------------------------------------

def bar(frac: float, width: int = 28) -> str:
    n = max(0, min(width, int(round(frac * width))))
    return "█" * n + "·" * (width - n)


def metrics(flat: list[Press], cflat: list[Press], keys: set[str],
            prm: Params) -> dict:
    """Every number for one (key set, params) combination."""
    r = simulate(flat, prm, keys)
    c = simulate_chords(cflat, prm, keys) if cflat else None
    keys_total = sum(len(ps) for _m, ps in flat)
    n = r["total"] or 1
    out = {
        "presses": r["total"],
        "fp": 1000 * r["misfires"] / n,
        "fp_n": r["misfires"],
        "fp_cross": r["cause"].get("cross", 0),
        "fp_same": r["cause"].get("same", 0),
        "timeout": r["cause"].get("timeout", 0),
        "deferred": 100 * r["deferred"] / n,
        "share": 100 * r["total"] / keys_total if keys_total else 0,
    }
    # Always present, so callers never have to guard: None means "no chord
    # drill recorded for this key set", which is different from 0% failure.
    out.update({"fn_cross": None, "fn_same": None,
                "fn_cross_n": (0, 0), "fn_same_n": (0, 0)})
    if c:
        ct, cf = c["cross"]
        st, sf = c["same"]
        out.update({"fn_cross": 100 * cf / ct if ct else None,
                    "fn_same": 100 * sf / st if st else None,
                    "fn_cross_n": (cf, ct), "fn_same_n": (sf, st)})
    return out


def print_grid(flat, chord_groups, keys, drill, base, terms, idles, label) -> None:
    cflat = chord_groups.get(drill, [])
    print("=" * 74)
    print(f"  GRID — {label}")
    print("=" * 74)
    if not cflat:
        print(f"  (no '{drill}' drill in this recording; false negatives unavailable)")
    print(f"  {'term':>5} {'idle':>5} | {'FP/1k':>7} {'n':>4} {'timeout':>8} | "
          f"{'FN cross':>9} {'FN same':>8} | {'defer':>6}")
    for t in terms:
        for i in idles:
            m = metrics(flat, cflat, keys, replace(base, tapping_term=t, prior_idle=i))
            fc = f"{m['fn_cross']:.0f}%" if m.get("fn_cross") is not None else "  -"
            fs = f"{m['fn_same']:.0f}%" if m.get("fn_same") is not None else "  -"
            print(f"  {t:>5.0f} {i:>5.0f} | {m['fp']:>7.1f} {m['fp_n']:>4} "
                  f"{m['timeout']:>8} | "
                  f"{fc:>9} {fs:>8} | {m['deferred']:>5.0f}%")
        print(f"  {'-' * 68}")


def print_compare(flat, chord_groups, base) -> None:
    cols = [("home row", DEFAULT_HRM, "chords"),
            ("bottom row", BOTTOM_HRM, "chords_bot")]
    res = [(lab, metrics(flat, chord_groups.get(dr, []), set(ks), base))
           for lab, ks, dr in cols]
    print("=" * 74)
    print("  COMPARE — home row vs bottom row")
    print("=" * 74)
    print(f"  tapping-term={base.tapping_term:.0f}  quick-tap={base.quick_tap:.0f}  "
          f"require-prior-idle={base.prior_idle:.0f}")
    print()
    print(f"  {'':<26}" + "".join(f"{lab:>16}" for lab, _ in res))
    rows = [
        ("mod keys typed", lambda m: f"{m['presses']:,}"),
        ("share of keystrokes", lambda m: f"{m['share']:.1f}%"),
        ("misfires", lambda m: f"{m['fp_n']} ({m['fp']:.1f}/1k)"),
        ("  cross-hand roll", lambda m: str(m["fp_cross"])),
        ("  same-hand roll", lambda m: str(m["fp_same"])),
        ("  held past term", lambda m: str(m["timeout"])),
        ("chords fail cross-hand",
         lambda m: f"{m['fn_cross_n'][0]}/{m['fn_cross_n'][1]} ({m['fn_cross']:.0f}%)"
         if m.get("fn_cross") is not None else "no drill"),
        ("chords fail same-hand",
         lambda m: f"{m['fn_same_n'][0]}/{m['fn_same_n'][1]} ({m['fn_same']:.0f}%)"
         if m.get("fn_same") is not None else "no drill"),
        ("output deferred", lambda m: f"{m['deferred']:.0f}%"),
    ]
    for name, fn in rows:
        print(f"  {name:<26}" + "".join(f"{fn(m):>16}" for _, m in res))
    print()


SEARCH_TERMS = [140, 160, 180, 200, 230, 280]
SEARCH_IDLES = [120, 150, 180, 220, 250]


CROSS_SHARE = 0.8   # assumed split of real modifier use, bilateral discipline

# Timeout misfires are weighted above roll misfires when scoring. They are not
# more frequent, they are more fragile: they only appear once tapping-term drops
# below your normal hold duration, so small drift in how long you hold a key
# swings the rate a lot. They are also the baffling kind, with no roll to blame.
TIMEOUT_WEIGHT = 2.0


def errors_per_day(m, kpd, cpd, tw=TIMEOUT_WEIGHT):
    """Both failure modes converted to a common unit: mistakes per day.

    Ranking on misfires alone is wrong — it rewards a huge require-prior-idle
    that suppresses misfires by making the modifier nearly unreachable.
    """
    n = m["presses"] or 1
    weighted = m["fp_n"] + (tw - 1.0) * m["timeout"]
    mis = kpd * (m["share"] / 100) * (weighted / n)
    fc = (m.get("fn_cross") or 0) / 100
    fs = (m.get("fn_same") or 0) / 100
    chd = cpd * (CROSS_SHARE * fc + (1 - CROSS_SHARE) * fs)
    return mis, chd, mis + chd


def metrics_grid(flat, cflat, keys, base) -> dict:
    """Simulate the whole (term x idle) grid once.

    kpd/cpd only affect scoring, never the simulation, so the grid is computed
    once and scored many times — the robustness check would otherwise re-run
    1500 simulations.
    """
    return {(t, i): metrics(flat, cflat, keys,
                            replace(base, tapping_term=t, prior_idle=i))
            for t in SEARCH_TERMS for i in SEARCH_IDLES}


def best_from_grid(grid: dict, kpd: int, cpd: int, tw=TIMEOUT_WEIGHT):
    """Minimise total mistakes per day, then latency."""
    scored = [(round(errors_per_day(m, kpd, cpd, tw)[2], 3), m["deferred"], t, i, m)
              for (t, i), m in grid.items()]
    scored.sort(key=lambda r: r[:2])
    return scored[0]


def robustness(g_home: dict, g_bot: dict, tw=TIMEOUT_WEIGHT):
    """Does the winner survive plausible volume assumptions, or is it an
    artifact of the two constants we had to guess?"""
    wins = {"home": 0, "bottom": 0}
    n = 0
    for kpd in (8000, 15000, 20000, 30000, 45000):
        for cpd in (100, 300, 800, 1500, 3000):
            h = errors_per_day(best_from_grid(g_home, kpd, cpd, tw)[4],
                               kpd, cpd, tw)[2]
            b = errors_per_day(best_from_grid(g_bot, kpd, cpd, tw)[4],
                               kpd, cpd, tw)[2]
            wins["bottom" if b <= h else "home"] += 1
            n += 1
    top = max(wins, key=lambda k: wins[k])
    return wins[top], n, top


def fmt_top(counts: dict, limit: int = 12) -> str:
    if not counts:
        return "none"
    top = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:limit]
    return "  ".join(f"{k}\u00d7{v}" if v > 1 else k for k, v in top)


def print_key_table(fp: dict, fn: dict, keys: set[str]) -> None:
    """Per-key detail for the --row deep dive."""
    order = sorted(keys, key=lambda k: (FINGER.get(k, "?"), k))
    fk, nk = fp["by_key"], fn.get("by_key", {})
    print(f"  {'key':<5}{'finger':<11}{'presses':>9}{'mis':>5}{'/1k':>7}"
          f"{'chords':>8}{'fail':>6}{'rate':>7}")
    hand = {"L": [0, 0, 0, 0], "R": [0, 0, 0, 0]}
    for k in order:
        d = fk.get(k, {"presses": 0, "misfires": 0})
        c = nk.get(k, {"attempts": 0, "failed": 0})
        h = HAND.get(k, "?")
        if h in hand:
            for j, v in enumerate((d["presses"], d["misfires"],
                                   c["attempts"], c["failed"])):
                hand[h][j] += v
        rate = 1000 * d["misfires"] / d["presses"] if d["presses"] else 0
        fr = 100 * c["failed"] / c["attempts"] if c["attempts"] else 0
        flag = "  thin" if d["presses"] < 40 else ""
        print(f"  {glyph(k):<5}{FINGER.get(k, '?'):<11}{d['presses']:>9,}"
              f"{d['misfires']:>5}{rate:>7.2f}{c['attempts']:>8}{c['failed']:>6}"
              f"{fr:>6.0f}%{flag}")
    print(f"  {'-' * 65}")
    for h in ("L", "R"):
        p, m, a, f = hand[h]
        print(f"  {('left hand' if h == 'L' else 'right hand'):<16}{p:>9,}{m:>5}"
              f"{1000 * m / p if p else 0:>7.2f}{a:>8}{f:>6}"
              f"{100 * f / a if a else 0:>6.0f}%")
    print()
    print(f"  {'misfiring':<12}{fmt_top(fp['bigrams'], 8)}")
    print(f"  {'in context':<12}{fmt_top(fp['trigrams'], 8)}")
    print(f"  {'words':<12}{fmt_top(fp['words'], 6)}")
    if fn.get("bigrams"):
        print(f"  {'bad chords':<12}{fmt_top(fn['bigrams'], 8)}   (held + tapped)")
    print()


ROWS_META = [("bottom", BOTTOM_HRM, "chords_bot", "bottom row", "z x c v / m , . /"),
             ("home", DEFAULT_HRM, "chords", "home row", "a s d f / j k l ;")]


def analyse(typing, chords, base, kpd, cpd, tw):
    """Everything the report needs, computed once."""
    groups: dict[str, list[tuple[str, list[Press]]]] = {}
    for m, ps in chords:
        groups.setdefault(m, []).append((m, ps))

    R = {}
    for key, ks, drill, label, klist in ROWS_META:
        grid = metrics_grid(typing, groups.get(drill, []), set(ks), base)
        _s, _d, t, i, m = best_from_grid(grid, kpd, cpd, tw)
        prm = replace(base, tapping_term=t, prior_idle=i)
        R[key] = {"grid": grid, "t": t, "i": i, "m": m, "keys": set(ks),
                  "drill": drill, "label": label, "klist": klist, "prm": prm,
                  "fp": simulate(typing, prm, set(ks)),
                  "fn": simulate_chords(groups.get(drill, []), prm, set(ks))}

    rw, rn, win = robustness(R["home"]["grid"], R["bottom"]["grid"], tw)
    lose = "home" if win == "bottom" else "bottom"
    return {"R": R, "groups": groups, "win": win, "lose": lose,
            "W": R[win], "L": R[lose], "robust": (rw, rn),
            "stats": mode_stats([ps for _m, ps in typing]),
            "typing": typing, "chords": chords, "base": base,
            "kpd": kpd, "cpd": cpd, "tw": tw,
            "keys_all": (sum(len(ps) for _m, ps in typing)
                         + sum(len(ps) for _m, ps in chords))}


# Thresholds the recommendation is judged against. They are opinions, stated
# openly so you can disagree with a specific number rather than the conclusion.
CRITERIA = [
    ("misfires per day", 2.0, "a letter coming out as a modifier is a stray "
                              "command, not a typo"),
    ("cross-hand chords lost", 5.0, "these are the modifiers you will actually "
                                    "reach for"),
    ("same-hand chords lost", 15.0, "recoverable by training cross-hand habits"),
    ("output deferred", 25.0, "share of mod presses whose character appears late"),
    ("timeout misfires", 0.0, "misfiring with no roll to blame is the confusing "
                              "kind"),
]


def score_row(A, key):
    """One dict per criterion: value, target, pass/fail, whether data exists.

    A criterion with no data behind it is reported as unknown and never counts
    as a pass — an unrecorded chord drill is not evidence of good chords.
    """
    m = A["R"][key]["m"]
    # Unweighted on purpose: the weighting steers the parameter search, but a
    # criterion called "misfires per day" must report the real count. Fragility
    # is captured by the separate timeout criterion.
    mis = errors_per_day(m, A["kpd"], A["cpd"], 1.0)[0]
    raw = [(mis, True, ""),
           (m["fn_cross"], m["fn_cross"] is not None, "%"),
           (m["fn_same"], m["fn_same"] is not None, "%"),
           (m["deferred"], True, "%"),
           (float(m["timeout"]), True, "")]
    return [{"name": name, "val": v, "limit": lim, "unit": unit, "data": has,
             "ok": bool(has and v <= lim), "why": why}
            for (name, lim, why), (v, has, unit) in zip(CRITERIA, raw)]


def recommend(A):
    """home | bottom | none, with the checklist behind it.

    Misfires per day is a gate, not just one vote. A letter that comes out as a
    modifier fires a command you did not ask for, and no amount of good chord
    behaviour compensates for that happening several times a day.
    """
    scored = {k: score_row(A, k) for k in ("home", "bottom")}
    passed = {k: sum(1 for c in v if c["ok"]) for k, v in scored.items()}
    best = A["win"]
    gate_ok = scored[best][0]["ok"]       # criterion 0 is misfires per day
    if not gate_ok:
        return "none", scored, passed, "avoid"
    if passed[best] == len(CRITERIA):
        return best, scored, passed, "adopt"
    return best, scored, passed, "try"


def misfire_traces(A, row, limit=8):
    """Real event timelines for each misfire, ms from the mod key's press."""
    d = A["R"][row]
    out = []
    for _mode, raw in A["typing"]:
        ps = sorted(raw, key=lambda p: p.down)
        last, lsame = None, {}
        for idx, p in enumerate(ps):
            if p.code in d["keys"]:
                v, _why, cat, other = resolve(idx, ps, d["prm"], d["keys"],
                                              last, lsame.get(p.code))
                if v == "hold":
                    if other is not None:
                        ev = sorted([
                            (0.0, f"{glyph(p.code)}↓"),
                            (other.down - p.down, f"{glyph(other.code)}↓"),
                            (other.up - p.down, f"{glyph(other.code)}↑"),
                            (p.up - p.down, f"{glyph(p.code)}↑")])
                        tl = "  ".join(f"{nm} {t:+.0f}" for t, nm in ev)
                    else:
                        tl = (f"{glyph(p.code)}↓ +0    held {p.dur:.0f} ms "
                              f"with no interrupting key")
                    out.append((word_at(ps, idx), tl, glyph(p.code),
                                glyph(other.code) if other else None, cat))
                lsame[p.code] = p.down
            if p.code not in MODIFIERS:
                last = p.down
        if len(out) >= limit:
            break
    return out[:limit]


def config_snippet(A):
    W, base = A["W"], A["base"]
    return ["hrm: home_row_mod {",
            '    compatible = "zmk,behavior-hold-tap";',
            "    #binding-cells = <2>;",
            '    flavor = "balanced";',
            f"    tapping-term-ms = <{W['t']:.0f}>;",
            f"    quick-tap-ms = <{base.quick_tap:.0f}>;",
            f"    require-prior-idle-ms = <{W['i']:.0f}>;",
            "    hold-trigger-key-positions = <KEYS_OPPOSITE THUMBS>;",
            "    hold-trigger-on-release;",
            "    bindings = <&kp>, <&kp>;",
            "};"]


def fragility_note(A):
    """Is the chosen tapping-term below the user's normal hold duration?"""
    W = A["W"]
    durs = sorted(p.dur for _m, ps in A["typing"] for p in ps
                  if p.code in W["keys"])
    if not durs:
        return None
    p95 = pct(durs, .95)
    if W["t"] >= p95:
        return None
    over = sum(1 for x in durs if x > W["t"])
    return (f"tapping-term {W['t']:.0f} sits below your p95 hold of {p95:.0f} ms. "
            f"{over} of {len(durs):,} presses ({100 * over / len(durs):.1f}%) "
            f"exceed it and misfire on the timer alone; "
            f"{pct(durs, .99):.0f}+ removes that class.")


HEAT = [(0.0, "·"), (2.0, "▁"), (5.0, "▃"),
        (10.0, "▅"), (float("inf"), "█")]


def _heat(rate):
    if rate is None:
        return "?"
    for lim, ch in HEAT:
        if rate <= lim:
            return ch
    return "█"


def _grade(v, bands):
    for g, lim in bands:
        if v <= lim:
            return g
    return "F"


def _buckets(vals, step, cap):
    b: dict[int, int] = {}
    for v in vals:
        k = min(int(v // step) * step, cap)
        b[k] = b.get(k, 0) + 1
    return b


def _hist(vals, thresh, step, cap, width=30, note="cumulative"):
    """One distribution with a threshold marked and a cumulative column."""
    b = _buckets(vals, step, cap)
    peak, cum = max(b.values()), 0
    for k in range(0, cap + step, step):
        n = b.get(k, 0)
        cum += n
        mark = "  <== threshold" if k <= thresh < k + step else ""
        lab = f"{k:>4}+" if k == cap else f"{k:>4} "
        print(f"    {lab} {'█' * int(width * n / peak):<{width}}"
              f"{100 * cum / len(vals):>5.1f}%{mark}")


def _hist2(a, b, thresh, step, cap, width=22):
    """Two distributions side by side, so their overlap is visible."""
    ba, bb = _buckets(a, step, cap), _buckets(b, step, cap)
    # Each column is scaled to its own peak. The question is where the two
    # distributions sit relative to the threshold, not how many samples each
    # has — sharing a peak would flatten the smaller series to nothing.
    pa, pb = max(ba.values()), max(bb.values())
    half = width // 2
    for k in range(0, cap + step, step):
        na, nb = ba.get(k, 0), bb.get(k, 0)
        mark = "  <== tapping-term" if k <= thresh < k + step else ""
        lab = f"{k:>4}+" if k == cap else f"{k:>4} "
        print(f"    {lab} {'█' * round(half * na / pa):<{half}}  "
              f"{'█' * round(half * nb / pb):<{half}}{mark}")


def _section(n, title, W):
    print()
    print("━" * W)
    print(f"  {n}. {title}")
    print("━" * W)


def print_report(A, W) -> None:
    """One report, ordered: the recommendation first, then the evidence."""
    st, Wd, Ld = A["stats"], A["W"], A["L"]
    kpd, cpd, tw = A["kpd"], A["cpd"], A["tw"]
    rw, rn = A["robust"]
    pick, scored, passed, strength = recommend(A)
    fg = fragility_note(A)

    def eday(d):
        return errors_per_day(d["m"], kpd, cpd, tw)

    print("═" * W)
    print("  HOME ROW MOD TUNER")
    print(f"  {A['keys_all']:,} keystrokes · "
          f"{len({m for m, _ in A['typing']})} typing tabs + "
          f"{len(A['groups'])} chord drills")
    print(f"  {st['wpm']:.0f} wpm active, {st['raw']:.0f} wpm wall clock · "
          f"median gap {st['gap']:.0f} ms · "
          f"{st['inv']:.2f}% released out of order")
    print("═" * W)

    # ---- 1. recommendation ----------------------------------------------
    _section(1, "RECOMMENDATION", W)
    if pick == "none":
        print("  ✗  Use NEITHER placement. Put the modifiers on a held layer.")
        print()
        print("     A thumb key activates a layer where the home row becomes plain")
        print("     modifiers. No dual-role keys, so no tap/hold decision, so no")
        print(f"     misfires by construction.")
        print()
        gate = scored[A["win"]][0]
        print(f"     The best dual-role option ({Wd['label']}) would still fire "
              f"{gate['val']:.1f}")
        print(f"     unintended modifier commands a day, against a target of "
              f"{gate['limit']:g}. That")
        print(f"     is the one criterion nothing else compensates for.")
    else:
        verb = "Use" if strength == "adopt" else "Worth trying:"
        print(f"  ✓  {verb} {Wd['label'].upper()} MODS   {Wd['klist']}")
        print()
        print(f"     tapping-term {Wd['t']:.0f} · quick-tap "
              f"{A['base'].quick_tap:.0f} · require-prior-idle {Wd['i']:.0f} · "
              f"flavor balanced")
        if strength == "try":
            print()
            print("     Flagged 'worth trying' rather than 'use': it clears most")
            print("     criteria but not all. Expect to iterate on real firmware.")
    print()
    print(f"  {'criterion':<26}{'target':>8}{Wd['label']:>12}{Ld['label']:>12}")

    def cell(c):
        if not c["data"]:
            return "no drill"
        return f"{c['val']:.1f}{c['unit']} " + ("✓" if c["ok"] else "✗")

    for cw, cl in zip(scored[A["win"]], scored[A["lose"]]):
        print(f"  {cw['name']:<26}{'≤' + format(cw['limit'], 'g'):>8}"
              f"{cell(cw):>12}{cell(cl):>12}")
    print(f"  {'-' * 58}")
    print(f"  {'criteria met':<26}{len(CRITERIA):>8}"
          f"{passed[A['win']]:>10}  {passed[A['lose']]:>10}")
    print()
    fails = [c for c in scored[A["win"]] if not c["ok"]]
    if fails:
        print(f"  {Wd['label']} does not clear:")
        for c in fails:
            if not c["data"]:
                print(f"    {c['name']} — no chord drill recorded, so this is "
                      f"unknown, not passing")
            else:
                print(f"    {c['name']} {c['val']:.1f}{c['unit']} vs target "
                      f"{c['limit']:g}{c['unit']} — {c['why']}")
    print()
    print("  Thresholds are opinions, listed so you can argue with a number")
    print("  rather than the conclusion. Nothing here reaches zero; only a held")
    print("  layer does, by construction.")

    # ---- 2. the two placements side by side -----------------------------
    _section(2, "HOME ROW vs BOTTOM ROW", W)
    print(f"  {'':<26}{Wd['label']:>12}{Ld['label']:>12}")
    rows = [("best tapping-term", lambda d: f"{d['t']:.0f}", ""),
            ("best require-prior-idle", lambda d: f"{d['i']:.0f}", ""),
            ("mistakes / day", lambda d: f"{eday(d)[2]:.1f}", "lower is better"),
            ("  misfires", lambda d: f"{eday(d)[0]:.1f}", "letter → modifier"),
            ("  failed chords", lambda d: f"{eday(d)[1]:.1f}",
             "modifier → letter"),
            ("misfires per 1000", lambda d: f"{d['m']['fp']:.1f}", ""),
            ("  cross-hand roll", lambda d: str(d["m"]["fp_cross"]),
             "rolled into the other hand"),
            ("  same-hand roll", lambda d: str(d["m"]["fp_same"]),
             "0 unless positional is off"),
            ("  held past term", lambda d: str(d["m"]["timeout"]),
             f"weighted ×{tw:g} when scoring"),
            ("output deferred", lambda d: f"{d['m']['deferred']:.0f}%",
             "character appears late"),
            ("keystroke exposure", lambda d: f"{d['m']['share']:.1f}%",
             "share landing on a mod key")]
    for lbl, f, note in rows:
        print(f"  {lbl:<26}{f(Wd):>12}{f(Ld):>12}"
              + (f"   {note}" if note else ""))
    print()
    print(f"  Winner holds in {rw}/{rn} volume assumptions "
          f"(--keys-per-day {kpd:,},")
    print(f"  --chords-per-day {cpd:,}). Below about 20/25, trust the raw rates")
    print("  and not the ranking.")
    if fg:
        print()
        print(f"  CAUTION  {fg}")

    # ---- 3. at a glance --------------------------------------------------
    _section(3, "AT A GLANCE", W)
    cards = [("roll discipline", st["inv"], "% of pairs released out of order",
              [("A", 1.5), ("B", 3), ("C", 5), ("D", 8)]),
             ("misfire rate", Wd["m"]["fp"], "per 1000 mod presses",
              [("A", 0.5), ("B", 2), ("C", 5), ("D", 10)]),
             ("chord reliability", Wd["m"]["fn_same"] or 0,
              "% of same-hand chords lost",
              [("A", 2), ("B", 5), ("C", 10), ("D", 25)]),
             ("latency", Wd["m"]["deferred"], "% of mod presses shown late",
              [("A", 5), ("B", 12), ("C", 25), ("D", 40)])]
    bars = {"A": "████▏", "B": "███▏ ", "C": "██▏  ", "D": "█▏   ", "F": "▏    "}
    for name, val, unit, bands in cards:
        g = _grade(val, bands)
        print(f"    {g}  {bars[g]}  {name:<20}{val:>6.1f}  {unit}")

    # ---- 4. how you type -------------------------------------------------
    _section(4, "HOW YOU TYPE", W)
    print(f"  {'tab':<19}{'keys':>7}{'wpm':>6}{'gap':>7}{'overlap':>9}"
          f"{'out-of-order':>14}")
    tg: dict[str, list[list[Press]]] = {}
    for m, ps in A["typing"]:
        tg.setdefault(m, []).append(ps)
    worst = max(tg, key=lambda m: mode_stats(tg[m])["inv"])
    for m in [k for k in MODE_LABELS if k in tg]:
        s = mode_stats(tg[m])
        tag = "   <-- your risk area" if m == worst else ""
        print(f"  {MODE_LABELS[m]:<19}{s['keys']:>7,}{s['wpm']:>6.0f}"
              f"{s['gap']:>5.0f}ms{s['over']:>8.1f}%{s['inv']:>13.2f}%{tag}")
    print(f"  {'all typing':<19}{st['keys']:>7,}{st['wpm']:>6.0f}"
          f"{st['gap']:>5.0f}ms{st['over']:>8.1f}%{st['inv']:>13.2f}%")
    for m in [k for k in MODE_LABELS if k in A["groups"]]:
        s = mode_stats([ps for _n, ps in A["groups"][m]])
        print(f"  {MODE_LABELS[m]:<19}{s['keys']:>7,}{'':>6}"
              f"{s['gap']:>5.0f}ms{s['over']:>8.1f}%{s['inv']:>13.2f}%"
              f"   by design")
    print()
    print("  out-of-order is the physical ceiling on misfires: how often you let")
    print("  go of the previous key after the next one. Chord drills overlap on")
    print("  purpose, so they are listed apart and never averaged in.")

    # ---- 5. all three thresholds ----------------------------------------
    _section(5, "WHERE YOUR THREE THRESHOLDS SIT", W)
    print("  Each parameter is one cut through a distribution of your own")
    print("  timings, which is why they are shown together: it is the same")
    print("  question asked three times.")

    gaps = []
    for _m, ps in A["typing"]:
        sp = sorted(ps, key=lambda p: p.down)
        gaps += [b.down - a.down for a, b in zip(sp, sp[1:])
                 if 0 <= b.down - a.down < 2000]
    print()
    print(f"  ── require-prior-idle = {Wd['i']:.0f} ms "
          f"{'─' * 8} gap between consecutive keys {'─' * 6}")
    _hist(gaps, Wd["i"], 25, 400)
    cover = 100 * sum(1 for g in gaps if g < Wd["i"]) / len(gaps)
    print(f"    {cover:.0f}% of transitions fall inside the window and resolve as "
          f"a tap at once.")
    print(f"    The other {100 - cover:.0f}% are the only moments a modifier can "
          f"arm, and so")
    print("    the only moments it can misfire.")

    typ_holds = [p.dur for _m, ps in A["typing"] for p in ps
                 if p.code in Wd["keys"]]
    chord_holds = []
    for _m, sess in A["groups"].get(Wd["drill"], []):
        sp = sorted(sess, key=lambda p: p.down)
        for i, p in enumerate(sp):
            if (p.code in Wd["keys"] and i + 1 < len(sp)
                    and sp[i + 1].down < p.up):
                chord_holds.append(p.dur)
    print()
    print(f"  ── tapping-term = {Wd['t']:.0f} ms "
          f"{'─' * 12} how long you hold a key {'─' * 10}")
    if chord_holds:
        print(f"    {'':5} {'normal typing':<22}  deliberate chords")
        _hist2(typ_holds, chord_holds, Wd["t"], 25, 400)
        over_t = sum(1 for x in typ_holds if x > Wd["t"])
        over_c = sum(1 for x in chord_holds if x > Wd["t"])
        print(f"    {over_t} of {len(typ_holds):,} typing presses "
              f"({100 * over_t / len(typ_holds):.1f}%) exceed it and misfire on")
        print("    the timer alone, with no roll to blame.")
        print(f"    {over_c} of {len(chord_holds)} deliberate holds "
              f"({100 * over_c / len(chord_holds):.0f}%) exceed it, so the hold "
              f"fires")
        print("    as you intended even if you release the keys out of order.")
        gap_lo, gap_hi = pct(typ_holds, .95), pct(chord_holds, .10)
        if gap_lo < gap_hi:
            print(f"    Your two distributions separate between {gap_lo:.0f} and "
                  f"{gap_hi:.0f} ms — that")
            print("    window is where the term wants to sit.")
        else:
            print(f"    Your distributions overlap (typing p95 {gap_lo:.0f} ms vs "
                  f"chord p10 {gap_hi:.0f} ms),")
            print("    so no term separates them cleanly. That is the core problem.")
    else:
        _hist(typ_holds, Wd["t"], 25, 400)
        print("    No chord drill recorded, so only your typing holds are shown.")
        print("    Record a chord drill to see whether a term separates the two.")

    repeats = []
    for _m, ps in A["typing"]:
        sp = sorted(ps, key=lambda p: p.down)
        for a, b in zip(sp, sp[1:]):
            if a.code == b.code and a.code in Wd["keys"]:
                d = b.down - a.down
                if 0 <= d < 2000:
                    repeats.append(d)
    print()
    print(f"  ── quick-tap = {A['base'].quick_tap:.0f} ms "
          f"{'─' * 12} same key pressed twice {'─' * 10}")
    if repeats:
        _hist(repeats, A["base"].quick_tap, 25, 400)
        inside = 100 * sum(1 for d in repeats
                           if d < A["base"].quick_tap) / len(repeats)
        print(f"    {inside:.0f}% of your {len(repeats)} same-key repeats fall "
              f"inside the window, so they")
        print("    stay taps instead of turning into a modifier. Doubles like")
        print("    'll' and held backspace are what this protects.")
    else:
        print("    You never pressed the same mod key twice in a row in this")
        print("    recording, so quick-tap-ms is doing nothing measurable. Leave")
        print(f"    it at {A['base'].quick_tap:.0f}.")

    # ---- 6. where it goes wrong -----------------------------------------
    _section(6, "WHERE IT GOES WRONG", W)
    print("  scale  · 0   ▁ <2   ▃ 2-5   ▅ 5-10   █ >10"
          "   misfires per 1000")
    print()
    for key, ks, _dr, label, _kl in ROWS_META[::-1]:
        cells = []
        for n, c in enumerate(ks):
            d = A["R"][key]["fp"]["by_key"].get(c)
            r = 1000 * d["misfires"] / d["presses"] if d and d["presses"] else None
            cells.append(f"{glyph(c)}{_heat(r)}")
            if n == 3:
                cells.append("  ")
        print(f"    {label:<12}" + "  ".join(cells))
    print()
    fingers: dict[str, dict] = {}
    for key in ("home", "bottom"):
        d = A["R"][key]
        for code, v in d["fp"]["by_key"].items():
            f = FINGER.get(code, "?")
            s = fingers.setdefault(f, {"pr": 0, "mis": 0, "att": 0, "fail": 0,
                                       "keys": {}})
            s["pr"] += v["presses"]
            s["mis"] += v["misfires"]
            k = s["keys"].setdefault(code, {"row": d["label"], "pr": 0, "mis": 0,
                                            "att": 0, "fail": 0})
            k["pr"] += v["presses"]
            k["mis"] += v["misfires"]
        for code, v in d["fn"].get("by_key", {}).items():
            f = FINGER.get(code, "?")
            s = fingers.setdefault(f, {"pr": 0, "mis": 0, "att": 0, "fail": 0,
                                       "keys": {}})
            s["att"] += v["attempts"]
            s["fail"] += v["failed"]
            k = s["keys"].setdefault(code, {"row": d["label"], "pr": 0, "mis": 0,
                                            "att": 0, "fail": 0})
            k["att"] += v["attempts"]
            k["fail"] += v["failed"]

    def per_k(n, d):
        return 1000 * n / d if d else 0.0

    print(f"  {'finger / key':<24}{'presses':>8}{'mis':>5}{'/1k':>7}"
          f"{'chords':>8}{'fail':>6}{'rate':>7}   verdict")
    for f, a in sorted(fingers.items(),
                       key=lambda x: -per_k(x[1]["mis"], x[1]["pr"])):
        fr = f"{100 * a['fail'] / a['att']:.0f}%" if a["att"] else "-"
        print(f"  {f:<24}{a['pr']:>8,}{a['mis']:>5}"
              f"{per_k(a['mis'], a['pr']):>7.1f}{a['att']:>8}{a['fail']:>6}{fr:>7}")
        for code, k in sorted(a["keys"].items(),
                              key=lambda x: -per_k(x[1]["mis"], x[1]["pr"])):
            rate = per_k(k["mis"], k["pr"])
            kfr = f"{100 * k['fail'] / k['att']:.0f}%" if k["att"] else "-"
            if k["pr"] < 40:
                v = "unproven, too few"
            elif rate > 5:
                v = "problem key"
            elif rate > 0:
                v = "occasional"
            else:
                v = "clean"
            print(f"    {glyph(code) + '   ' + k['row']:<22}{k['pr']:>8,}"
                  f"{k['mis']:>5}{rate:>7.1f}{k['att']:>8}{k['fail']:>6}{kfr:>7}"
                  f"   {v}")
    print()
    print(f"  {'misfiring':<13}{fmt_top(Wd['fp']['bigrams'], 8)}")
    print(f"  {'in context':<13}{fmt_top(Wd['fp']['trigrams'], 8)}")
    print(f"  {'in words':<13}{fmt_top(Wd['fp']['words'], 6)}")
    if Wd["fn"].get("bigrams"):
        print(f"  {'bad chords':<13}{fmt_top(Wd['fn']['bigrams'], 8)}"
              f"   held + tapped")

    # ---- 7. mechanism ----------------------------------------------------
    _section(7, "MECHANISM — every misfire as it happened", W)
    tr = misfire_traces(A, A["win"])
    if not tr:
        print("  None at the chosen config.")
    for word, tl, k, other, cat in tr:
        print(f"  {word}")
        print(f"    {tl}")
        if other:
            print(f"    '{other}' went down AND up while '{k}' was still held, "
                  f"opposite hand,")
            print(f"    so balanced flavor fired the hold.   [{cat}]")
        else:
            print(f"    No interrupting key — the tapping-term timer alone fired "
                  f"at {Wd['t']:.0f}.   [{cat}]")
        print()
    print("  Times are ms from the mod key's press. A roll misfire needs the other")
    print("  key down AND up before the mod key comes up.")

    # ---- 8. what to do ---------------------------------------------------
    _section(8, "WHAT TO DO", W)
    n = 1
    if fg:
        print(f"  {n}. Raise tapping-term. {fg}")
        n += 1
    same = Wd["m"]["fn_same"]
    if same:
        print(f"  {n}. Same-hand chords lose {same:.0f}%. They can only fire by "
              f"holding past the")
        print("     term, so drive modifiers cross-hand, or move the ones you use")
        print("     most to thumb keys where there is no tap/hold decision at all.")
        n += 1
    thin = sorted({glyph(c) for row in ("home", "bottom")
                   for c, v in A["R"][row]["fp"]["by_key"].items()
                   if v["presses"] < 40})
    if thin:
        print(f"  {n}. Record more before trusting {', '.join(thin)} — under 40 "
              f"presses each,")
        print("     so their rates are noise either way.")
        n += 1
    print(f"  {n}. Flash the config in section 9 and live with it for a week. The")
    print("     numbers here are a strong prior, not a substitute for your hands.")
    print(f"  {n + 1}. If you want zero rather than low, put the mods on a held")
    print("     layer and stop tuning timings.")
    print()
    print("  Deliberately not recommended: dropping the mod from a problem key.")
    print("  It reads well in the data and badly on a keyboard — the modifier has")
    print("  to live somewhere, these layouts are designed as mirrored sets, and")
    print("  a key flagged on one or two events is noise, not a verdict. Section 6")
    print("  names your problem keys so you can watch them, not retire them.")

    # ---- 9. config -------------------------------------------------------
    _section(9, "CONFIG", W)
    for ln in config_snippet(A):
        print(f"    {ln}")
    print()
    print("  Replace KEYS_OPPOSITE with your board's opposite-hand key positions.")

    # ---- 10. limits ------------------------------------------------------
    _section(10, "WHAT THIS CANNOT TELL YOU", W)
    n_pr = Wd["m"]["presses"]
    print(f"  · {Wd['m']['fp_n']} misfires in {n_pr:,} presses. Rule of three "
          f"bounds the true rate")
    print(f"    under {3000 / n_pr:.1f} per 1000 — a bound, never a proof of zero.")
    print(f"  · mistakes/day assumes {kpd:,} keystrokes and {cpd:,} chords a day, "
          f"both")
    print("    guesses. Override with --keys-per-day / --chords-per-day.")
    print("  · The chord drill is self-paced, which flatters a large")
    print("    require-prior-idle. Real use gives you no pause before a modifier.")
    print("  · Simulated from ZMK's documented behaviour, not its source. Treat")
    print("    it as a strong prior, not ground truth.")
    print()
    print("  Drill down:  --row home | --row bottom | --grid | --compare")
    print("═" * W)


def build_parser() -> argparse.ArgumentParser:
    """All command-line options, kept apart so main() stays readable."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recording", help="JSON exported from record.html")
    ap.add_argument("--hrm", default=None,
                    help="comma-separated key codes carrying mods")
    ap.add_argument("--row", choices=sorted(ROWS), default=None,
                    help="deep-dive one row (default: overview of both)")
    ap.add_argument("--keys-per-day", type=int, default=20000,
                    help="for translating rates into misfires/day")
    ap.add_argument("--timeout-weight", type=float, default=TIMEOUT_WEIGHT,
                    help="how much worse a timeout misfire is than a roll "
                         "misfire when scoring (default 2, use 1 to disable)")
    ap.add_argument("--chords-per-day", type=int, default=800,
                    help="modifier chords you hit per day (Shift for capitals "
                         "dominates this); for failed-chords/day")
    ap.add_argument("--tapping-term", type=float, default=280.0)
    ap.add_argument("--quick-tap", type=float, default=175.0)
    ap.add_argument("--prior-idle", type=float, default=150.0)
    ap.add_argument("--no-positional", action="store_true",
                    help="disable hold-trigger-key-positions")
    ap.add_argument("--no-trigger-on-release", action="store_true")
    ap.add_argument("--top", type=int, default=12, help="misfire examples to list")
    ap.add_argument("--grid", action="store_true",
                    help="joint sweep: false positives AND false negatives over "
                         "tapping-term x require-prior-idle")
    ap.add_argument("--compare", action="store_true",
                    help="home row vs bottom row side by side at the given params")
    ap.add_argument("--terms", default="100,120,140,160,180,200,230,280",
                    help="tapping-term values for --grid")
    ap.add_argument("--idles", default="120,150,180,220",
                    help="require-prior-idle values for --grid")
    ap.add_argument("--exclude", default="",
                    help="comma-separated session modes to drop, e.g. words_bot "
                         "(that passage over-represents the bottom row)")
    return ap


def load_recording(path: str, drop: set[str]):
    """Read an export and split sessions into typing vs chord drills.

    Returns (typing, chords), each a list of (mode, presses). Sessions stay
    separate on purpose: browser timestamps restart on every page load, so
    merging them would fabricate adjacencies. See simulate().
    """
    with open(path) as f:
        data = json.load(f)

    typing: list[tuple[str, list[Press]]] = []
    chords: list[tuple[str, list[Press]]] = []
    for s in data["sessions"]:
        ps = pair_events(s["events"])
        if len(ps) < 2:
            continue
        mode = str(s.get("mode", "?"))
        if mode in drop:
            continue
        (chords if mode.startswith("chords") else typing).append((mode, ps))
    return typing, chords


def print_deep_dive(typing, chords, hrm, base, args, W) -> None:
    """Full report for one key placement, driven by the flags given."""
    pr = profile(typing, hrm)
    wpm = (pr["keys"] / 5) / (pr["span"] / 60) if pr["span"] > 5 else 0

    print_by_tab(typing, chords, W)
    print("=" * W)
    print("  GAP DISTRIBUTION  (all tabs combined)")
    print("=" * W)
    ik = pr["ikis"]
    print("  inter-key gap (press to press)")
    for label, q in (("p10", .10), ("p25", .25), ("median", .50),
                     ("p75", .75), ("p90", .90), ("p95", .95)):
        print(f"    {label:<8} {pct(ik, q):6.0f} ms")
    print()
    du = pr["durs"]
    print(f"  key hold duration  "
          f"    median {pct(du,.5):.0f} ms   p90 {pct(du,.9):.0f} ms")
    print()
    print(f"  require-prior-idle-ms must exceed most of this distribution to")
    print(f"  suppress rolls: p90 is {pct(ik, .90):.0f} ms, "
          f"p95 is {pct(ik, .95):.0f} ms.")
    print()
    if pr["inv_bigrams"]:
        top = sorted(pr["inv_bigrams"].items(), key=lambda x: -x[1])[:10]
        print("  pairs you most often release out of order, starting on a mod key:")
        print("    " + "  ".join(f"{k}\u00d7{v}" for k, v in top))
    print()

    print("=" * W)
    print("  FALSE POSITIVES — letters that would become modifiers")
    print("=" * W)
    print(f"  flavor=balanced  tapping-term={base.tapping_term:.0f}  "
          f"quick-tap={base.quick_tap:.0f}  require-prior-idle={base.prior_idle:.0f}")
    positional = "opposite hand" if base.positional else "off"
    print(f"  hold-trigger-key-positions={positional}"
          f"  hold-trigger-on-release={base.hold_trigger_on_release}")
    print("  These are the params you passed (or the defaults), NOT the searched")
    print("  optimum. Run with no flags to see the best settings for this row.")
    print()
    res = simulate(typing, base, hrm)
    rate = 1000 * res["misfires"] / res["total"] if res["total"] else 0
    dfr = 100 * res["deferred"] / res["total"] if res["total"] else 0
    print(f"  mod keys typed         {res['total']:,}")
    print(f"  MISFIRES         "
          f"      {res['misfires']:,}  ({rate:.2f} per 1000 presses)")
    print(f"  output deferred        {dfr:.1f}% of presses (character appears late)")
    print()
    cz = res["cause"]
    print(f"  {'cause':<34}{'count':>7}{'per 1000':>11}")
    lbl = [("cross", "cross-hand roll", ""),
           ("same", "same-hand roll",
            "blocked by hold-trigger-key-positions" if base.positional else ""),
           ("timeout", "held past tapping-term", "")]
    for k, name, note in lbl:
        n = cz.get(k, 0)
        r_ = 1000 * n / res["total"] if res["total"] else 0
        tail = f"   ({note})" if note and n == 0 else ""
        print(f"  {name:<34}{n:>7}{r_:>11.2f}{tail}")
    print(f"  {'-' * 52}")
    print(f"  {'TOTAL':<34}{res['misfires']:>7}{rate:>11.2f}")
    print()
    print(f"  {'by tab':<20}{'mod presses':>13}{'misfires':>10}{'per 1000':>11}")
    for m in [k for k in MODE_LABELS if k in res["per"]]:
        d = res["per"][m]
        rr = 1000 * d["misfires"] / d["presses"] if d["presses"] else 0
        print(f"  {MODE_LABELS.get(m, m):<20}{d['presses']:>13,}"
              f"{d['misfires']:>10}{rr:>11.2f}")
    print()
    fn_all = simulate_chords([(m, ps) for m, ps in chords], base, hrm)
    print_key_table(res, fn_all, hrm)
    if res["examples"]:
        print(f"  first {min(args.top, len(res['examples']))} misfires in context:")
        for m, p, ctx, why in res["examples"][:args.top]:
            print(f"    {ctx:<10} {glyph(p.code)} held {p.dur:5.0f} ms   "
                  f"{MODE_LABELS.get(m, m):<17} {why}")
        print()

    print("=" * W)
    print("  PARAMETER SWEEP — misfires per 1000 home row presses")
    print("=" * W)
    idles = [0, 40, 60, 80, 100, 120, 150, 180, 220]
    terms = [160, 180, 200, 230, 280, 320]
    flat = typing

    grid: dict[tuple[float, float], float] = {}
    for t in terms:
        for idle in idles:
            r = simulate(flat, replace(base, tapping_term=t, prior_idle=idle), hrm)
            grid[(t, idle)] = 1000 * r["misfires"] / r["total"] if r["total"] else 0.0

    print("            require-prior-idle-ms")
    print("  term  " + "".join(f"{i:>7}" for i in idles))
    for t in terms:
        print(f"  {t:>4}  " + "".join(f"{grid[(t, i)]:>7.1f}" for i in idles))
    print()

    rows_identical = all(
        abs(grid[(t, i)] - grid[(terms[0], i)]) < 1e-9 for t in terms for i in idles)
    if rows_identical:
        print("  NOTE: every tapping-term row is identical. That is not a bug — with")
        print("  hold-trigger-on-release, a roll is decided by the other key's release")
        print(f"  (~{pct(du, .5):.0f} ms in your data), long before any tapping")
        print("  term expires. During")
        print("  normal typing tapping-term-ms does nothing. Only")
        print("  require-prior-idle-ms")
        print("  protects you. This is what 'timeless home row mods' actually means.")
        print()

    # smallest require-prior-idle that eliminates misfires at the chosen term
    clean = [i for i in idles if grid[(base.tapping_term, i)] == 0.0]
    best_idle = clean[0] if clean else None

    print("=" * W)
    print("  RECOMMENDATION")
    print("=" * W)
    if best_idle is None:
        print(f"  At tapping-term {base.tapping_term:.0f} no require-prior-idle value")
        print("  tested reached zero misfires. Run with no flags to search the")
        print("  full grid — a shorter tapping-term usually does better — or put")
        print("  the mods on a held layer for zero by construction.")
    else:
        headroom = pct(ik, .90)
        print(f"  require-prior-idle-ms = {best_idle:.0f}")
        print(f"    smallest value with zero misfires in your sample.")
        print(f"    your p90 inter-key gap is {headroom:.0f} ms; urob's 10500/wpm rule")
        print(f"    would suggest {10500/wpm:.0f} ms at your {wpm:.0f} wpm.")
        if best_idle < headroom:
            print(f"    WARNING: {best_idle:.0f} is below your p90 gap "
                  "— thin margin. Consider")
            safer = next((i for i in idles if i >= headroom), idles[-1])
            print(f"    {safer:.0f} for safety.")
    print()

    if chords:
        print("=" * W)
        print("  FALSE NEGATIVES — would your intentional holds actually fire?")
        print("=" * W)
        idle_for_fn = best_idle if best_idle is not None else base.prior_idle
        groups: dict[str, list[tuple[str, list[Press]]]] = {}
        for m, ps in chords:
            groups.setdefault(m, []).append((m, ps))

        fn_summary: dict[str, dict] = {}
        for m, cflat in groups.items():
            keys = set(CHORD_KEYS.get(m, DEFAULT_HRM))
            label = "bottom row  z x c v / m , . /" if m == "chords_bot" \
                    else "home row  a s d f / j k l ;"
            print(f"  drill: {label}")
            print(f"  require-prior-idle held at {idle_for_fn:.0f} ms")
            print()
            print(f"  {'term':>6}   {'cross-hand chords':<24}{'same-hand chords':<24}")
            for t in terms:
                r = simulate_chords(cflat, replace(base, tapping_term=t,
                                                   prior_idle=idle_for_fn), keys)
                ct, cf = r["cross"]
                st, sf = r["same"]
                cs = f"{cf}/{ct} failed ({100*cf/ct:.0f}%)" if ct else "none recorded"
                ss = f"{sf}/{st} failed ({100*sf/st:.0f}%)" if st else "none recorded"
                print(f"  {t:>6}   {cs:<24}{ss:<24}")

            at_base = simulate_chords(
                cflat, replace(base, prior_idle=idle_for_fn), keys)
            fn_summary[m] = at_base

            # the release-order signature, which no timing can fix
            oo = tot = 0
            for _m, sess in cflat:
                sp = sorted(sess, key=lambda p: p.down)
                for i, p in enumerate(sp):
                    if p.code in keys and i + 1 < len(sp) and sp[i + 1].down < p.up:
                        tot += 1
                        if sp[i + 1].up > p.up:
                            oo += 1
            if tot:
                print()
                print(f"  released the HELD key before the tapped key: "
                      f"{oo}/{tot} ({100*oo/tot:.0f}%)")
                print("    No timing value can rescue these — the hold-tap never sees")
                print("    the interrupt complete, so it resolves as a tap.")
            print()

        print("  Same-hand chords can ONLY fire by holding past tapping-term — that is")
        print("  hold-trigger-key-positions doing its job. If that column stays bad at")
        print("  every term, either train a deliberate pause before same-hand chords,")
        print("  or move those modifiers to thumb keys.")
        print()

        print("=" * W)
        print("  SUMMARY — both error types, by hand")
        print("=" * W)
        print(f"  tapping-term={base.tapping_term:.0f}  "
              f"quick-tap={base.quick_tap:.0f}  "
              f"require-prior-idle={idle_for_fn:.0f}")
        print()
        print(f"  {'':<26}{'same-hand':>16}{'cross-hand':>16}{'total':>14}")
        cz = res["cause"]
        fp_same, fp_cross = cz.get("same", 0), cz.get("cross", 0) + cz.get("timeout", 0)
        n = res["total"] or 1
        fp_s = f"{fp_same} ({1000 * fp_same / n:.1f}/1k)"
        fp_c = f"{fp_cross} ({1000 * fp_cross / n:.1f}/1k)"
        fp_t = f"{res['misfires']} ({rate:.1f}/1k)"
        print(f"  {'false positives':<26}{fp_s:>16}{fp_c:>16}{fp_t:>14}")
        for m, r in fn_summary.items():
            st, sf = r["same"]
            ct, cf = r["cross"]
            tt, tf = r["total"], r["failed"]
            row = "false negatives" + (" (bottom)" if m == "chords_bot" else " (home)")
            fs = f"{sf}/{st} ({100*sf/st:.0f}%)" if st else "none"
            fc = f"{cf}/{ct} ({100*cf/ct:.0f}%)" if ct else "none"
            ft = f"{tf}/{tt} ({100*tf/tt:.0f}%)" if tt else "none"
            print(f"  {row:<26}{fs:>16}{fc:>16}{ft:>14}")
        print()
        print("  false positive = a letter you typed came out as a modifier")
        print("  false negative = a modifier you meant came out as a letter")
        print()
    else:
        print("  (No chord-drill session found — run that mode in record.html to")
        print("   also measure how often intentional modifiers would fail.)\n")


def main() -> int:
    args = build_parser().parse_args()

    hrm = (set(args.hrm.split(",")) if args.hrm
           else set(ROWS[args.row or "home"]))
    base = Params(tapping_term=args.tapping_term,
                  quick_tap=args.quick_tap,
                  prior_idle=args.prior_idle,
                  hold_trigger_on_release=not args.no_trigger_on_release,
                  positional=not args.no_positional)
    drop = {m.strip() for m in args.exclude.split(",") if m.strip()}

    typing, chords = load_recording(args.recording, drop)
    if not typing:
        print("No typing sessions found. Record the word, code or free "
              "typing tabs first.", file=sys.stderr)
        return 1

    W = 74
    if not args.grid and not args.compare and not args.row and not args.hrm:
        print_report(analyse(typing, chords, base, args.keys_per_day,
                             args.chords_per_day, args.timeout_weight), W)
        return 0

    if args.grid or args.compare:
        flat_all = typing
        groups: dict[str, list[tuple[str, list[Press]]]] = {}
        for m, ps in chords:
            groups.setdefault(m, []).append((m, ps))
        if drop:
            print(f"  (excluding sessions: {', '.join(sorted(drop))})\n")
        if args.compare:
            print_compare(flat_all, groups, base)
        if args.grid:
            terms = [float(x) for x in args.terms.split(",")]
            idles = [float(x) for x in args.idles.split(",")]
            row_keys = sorted(hrm)
            drill = "chords_bot" if set(row_keys) == set(BOTTOM_HRM) else "chords"
            label = ("bottom row  z x c v / m , . /"
                     if drill == "chords_bot" else "home row  a s d f / j k l ;")
            print_grid(flat_all, groups, hrm, drill, base, terms, idles, label)
        return 0

    print_deep_dive(typing, chords, hrm, base, args, W)
    return 0


if __name__ == "__main__":
    sys.exit(main())
