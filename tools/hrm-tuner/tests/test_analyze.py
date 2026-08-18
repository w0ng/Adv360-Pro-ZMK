"""Tests for the ZMK hold-tap simulator.

Run from the tool directory:

    python3 -m unittest discover -s tests -v

Stdlib only, no dependencies. The cases in ZmkSemantics are derived by hand
from https://zmk.dev/docs/keymaps/behaviors/hold-tap — if you change resolve(),
these are the contract it has to keep.
"""
import json
import os
import random
import sys
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyze import (                                             # noqa: E402
    BOTTOM_HRM, DEFAULT_HRM, FINGER, HAND, MODIFIERS, Params, Press,
    mode_stats, pair_events, resolve, simulate, simulate_chords, word_at,
)

HRM = set(DEFAULT_HRM)
STOCK = Params()          # urob's published values: 280 / 175 / 150


def verdict(presses, last_press_t=None, last_same_t=None, prm=STOCK):
    return resolve(0, presses, prm, HRM, last_press_t, last_same_t)[0]


class ZmkSemantics(unittest.TestCase):
    """One test per documented rule."""

    def test_cross_hand_roll_after_pause_is_a_hold(self):
        # d↓ j↓ j↑ d↑ — balanced flavor: the other key was pressed AND released
        # while held, and j is opposite-hand so positional allows it.
        self.assertEqual(
            verdict([Press("KeyD", 0, 120), Press("KeyJ", 40, 80)]), "hold")

    def test_require_prior_idle_forces_a_tap(self):
        # Same roll, but the previous keypress was 50 ms ago.
        self.assertEqual(
            verdict([Press("KeyD", 0, 120), Press("KeyJ", 40, 80)],
                    last_press_t=-50), "tap")

    def test_same_hand_roll_is_blocked_by_positional(self):
        self.assertEqual(
            verdict([Press("KeyD", 0, 120), Press("KeyF", 40, 80)]), "tap")

    def test_properly_nested_roll_is_a_tap(self):
        # d↓ j↓ d↑ j↑ — the hold-tap released first, so it never sees the
        # interrupt complete.
        self.assertEqual(
            verdict([Press("KeyD", 0, 60), Press("KeyJ", 40, 100)]), "tap")

    def test_long_hold_with_no_interrupt_is_a_hold(self):
        self.assertEqual(verdict([Press("KeyD", 0, 400)]), "hold")

    def test_deliberate_cross_hand_chord_is_a_hold(self):
        self.assertEqual(
            verdict([Press("KeyD", 0, 300), Press("KeyJ", 100, 160)]), "hold")

    def test_quick_tap_forces_a_tap(self):
        self.assertEqual(
            verdict([Press("KeyD", 0, 400)], last_same_t=-100), "tap")

    def test_thumb_counts_as_opposite_hand(self):
        self.assertEqual(
            verdict([Press("KeyD", 0, 120), Press("Space", 40, 80)]), "hold")

    def test_modifiers_do_not_reset_the_idle_window(self):
        # ZMK measures require-prior-idle from another NON-MODIFIER key, so a
        # Shift press must not arm the window. Callers filter it, so the only
        # prior key here is Shift -> last_press_t stays None -> hold.
        self.assertEqual(
            verdict([Press("KeyS", 0, 120), Press("KeyL", 40, 80)]), "hold")
        self.assertIn("ShiftLeft", MODIFIERS)

    def test_tapping_term_below_the_hold_rescues_an_early_release(self):
        # The finding that flipped the recommendation: if the timer fires before
        # the user releases, out-of-order release stops mattering.
        early = [Press("KeyD", 0, 200), Press("KeyJ", 40, 260)]
        self.assertEqual(verdict(early, prm=replace(STOCK, tapping_term=280)),
                         "tap")
        self.assertEqual(verdict(early, prm=replace(STOCK, tapping_term=140)),
                         "hold")

    def test_resolve_reports_the_interrupting_key(self):
        _v, _why, cat, other = resolve(
            0, [Press("KeyD", 0, 120), Press("KeyJ", 40, 80)],
            STOCK, HRM, None, None)
        self.assertEqual(cat, "cross")
        self.assertEqual(other.code, "KeyJ")


class SessionIndependence(unittest.TestCase):
    """Regression: browser timestamps restart at zero on every page load."""

    def _sessions(self):
        # Two sessions whose timestamp ranges overlap, as happens whenever a
        # recording spans more than one page load.
        a = [Press("KeyA", t, t + 90) for t in range(10_000, 11_000, 100)]
        b = [Press("KeyA", t, t + 90) for t in range(100, 1_100, 100)]
        return [("words", a), ("free", b)]

    def test_batched_equals_sum_of_parts(self):
        sess = self._sessions()
        both = simulate(sess, STOCK, HRM)
        apart = [simulate([s], STOCK, HRM) for s in sess]
        self.assertEqual(both["total"], sum(r["total"] for r in apart))
        self.assertEqual(both["misfires"], sum(r["misfires"] for r in apart))

    def test_backwards_jump_creates_no_phantom_interrupts(self):
        # Concatenating these naively made the forward scan pull in the other
        # session's keys as interrupts.
        r = simulate(self._sessions(), STOCK, HRM)
        self.assertEqual(r["cause"]["cross"], 0)

    def test_per_tab_totals_add_up(self):
        r = simulate(self._sessions(), STOCK, HRM)
        self.assertEqual(sum(v["presses"] for v in r["per"].values()), r["total"])
        self.assertEqual(sum(v["misfires"] for v in r["per"].values()),
                         r["misfires"])


class PairEvents(unittest.TestCase):
    def test_matches_down_to_up(self):
        ev = [{"t": 0, "c": "KeyA", "d": 1}, {"t": 90, "c": "KeyA", "d": 0}]
        (p,) = pair_events(ev)
        self.assertEqual((p.code, p.down, p.up), ("KeyA", 0, 90))

    def test_drops_unmatched_down(self):
        ev = [{"t": 0, "c": "KeyA", "d": 1}]
        self.assertEqual(pair_events(ev), [])

    def test_ignores_orphan_up(self):
        # Happens when a key was already held before the page took focus.
        ev = [{"t": 5, "c": "KeyA", "d": 0}, {"t": 10, "c": "KeyB", "d": 1},
              {"t": 90, "c": "KeyB", "d": 0}]
        self.assertEqual([p.code for p in pair_events(ev)], ["KeyB"])

    def test_output_is_sorted_by_press_time(self):
        ev = [{"t": 50, "c": "KeyB", "d": 1}, {"t": 0, "c": "KeyA", "d": 1},
              {"t": 60, "c": "KeyB", "d": 0}, {"t": 40, "c": "KeyA", "d": 0}]
        self.assertEqual([p.code for p in pair_events(ev)], ["KeyA", "KeyB"])


class WordContext(unittest.TestCase):
    def _word(self, text, i):
        codes = {" ": "Space"}
        ps = [Press(codes.get(c, "Key" + c.upper()), n * 100, n * 100 + 90)
              for n, c in enumerate(text)]
        return word_at(ps, i)

    def test_marks_the_key_in_its_word(self):
        self.assertEqual(self._word("lazy dog", 0), "[l]azy")

    def test_stops_at_word_boundaries(self):
        self.assertEqual(self._word("lazy dog", 5), "[d]og")

    def test_skips_modifier_keys(self):
        ps = [Press("ShiftLeft", 0, 200), Press("KeyA", 50, 140),
              Press("KeyL", 200, 290)]
        self.assertEqual(word_at(ps, 2), "a[l]")


class Maps(unittest.TestCase):
    def test_every_mod_candidate_has_a_hand_and_finger(self):
        for code in DEFAULT_HRM + BOTTOM_HRM:
            self.assertIn(code, HAND, code)
            self.assertIn(code, FINGER, code)

    def test_each_row_uses_eight_distinct_fingers(self):
        for row in (DEFAULT_HRM, BOTTOM_HRM):
            self.assertEqual(len({FINGER[c] for c in row}), 8)

    def test_hand_and_finger_agree(self):
        for code, finger in FINGER.items():
            if finger == "thumb":
                continue
            self.assertEqual(HAND[code], finger[0], code)


class ChordDrill(unittest.TestCase):
    def _drill(self, hold, tap, hold_ms=240, lead=70, tap_ms=75):
        ps = [Press(hold, 0, hold_ms), Press(tap, lead, lead + tap_ms)]
        return [("chords", ps)]

    def test_cross_hand_chord_succeeds_when_timer_fires_first(self):
        r = simulate_chords(self._drill("KeyF", "KeyJ"),
                            replace(STOCK, tapping_term=140), HRM)
        self.assertEqual(r["cross"], [1, 0])

    def test_same_hand_chord_needs_the_full_tapping_term(self):
        r = simulate_chords(self._drill("KeyA", "KeyC"), STOCK, HRM)
        self.assertEqual(r["same"], [1, 1])       # attempted, failed

    def test_misfire_causes_are_split_by_hand(self):
        cross = [("words", [Press("KeyD", 0, 120), Press("KeyJ", 40, 80)])]
        r = simulate(cross, STOCK, HRM)
        self.assertEqual((r["cause"]["cross"], r["cause"]["same"],
                          r["cause"]["timeout"]), (1, 0, 0))

    def test_positional_off_allows_same_hand_misfires(self):
        same = [("words", [Press("KeyD", 0, 120), Press("KeyF", 40, 80)])]
        self.assertEqual(simulate(same, STOCK, HRM)["cause"]["same"], 0)
        loose = replace(STOCK, positional=False)
        self.assertEqual(simulate(same, loose, HRM)["cause"]["same"], 1)

    def test_short_tapping_term_produces_timeout_misfires(self):
        held = [("words", [Press("KeyD", 0, 150)])]
        self.assertEqual(simulate(held, STOCK, HRM)["cause"]["timeout"], 0)
        short = replace(STOCK, tapping_term=100)
        self.assertEqual(simulate(held, short, HRM)["cause"]["timeout"], 1)

    def test_counts_are_split_by_hand(self):
        r = simulate_chords(self._drill("KeyF", "KeyJ") +
                            self._drill("KeyA", "KeyC"), STOCK, HRM)
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["cross"][0], 1)
        self.assertEqual(r["same"][0], 1)


class ModeStats(unittest.TestCase):
    def test_wpm_excludes_long_pauses(self):
        # 10 keys at 100 ms apart, then a 30 s gap, then 10 more. Wall clock
        # would report a fraction of the active rate.
        # mode_stats needs >5 s of active typing before it reports a rate.
        a = [Press("KeyA", t, t + 50) for t in range(0, 20_000, 100)]
        b = [Press("KeyA", t, t + 50) for t in range(50_000, 70_000, 100)]
        s = mode_stats([a + b])
        self.assertGreater(s["wpm"] / s["raw"], 1.4)

    def test_rate_is_zero_below_the_minimum_sample(self):
        tiny = [Press("KeyA", t, t + 50) for t in range(0, 500, 100)]
        self.assertEqual(mode_stats([tiny])["wpm"], 0.0)

    def test_out_of_order_release_is_counted(self):
        rolled = [Press("KeyD", 0, 120), Press("KeyJ", 40, 80)]
        self.assertAlmostEqual(mode_stats([rolled])["inv"], 100.0)
        nested = [Press("KeyD", 0, 60), Press("KeyJ", 40, 100)]
        self.assertAlmostEqual(mode_stats([nested])["inv"], 0.0)


class EndToEnd(unittest.TestCase):
    """A deterministic synthetic recording through the public entry point."""

    def _recording(self, path):
        random.seed(1234)
        codes = {c: "Key" + c.upper() for c in "abcdefghijklmnopqrstuvwxyz"}
        codes[" "] = "Space"
        text = "the quick brown fox jumps over a lazy dog " * 40
        t, ev = 1000.0, []
        for ch in text:
            t += max(30, random.gauss(95, 30))
            dur = max(25, random.gauss(90, 25))
            ev.append({"t": round(t, 2), "c": codes[ch], "d": 1})
            ev.append({"t": round(t + dur, 2), "c": codes[ch], "d": 0})
        with open(path, "w") as f:
            json.dump({"version": 1, "sessions": [
                {"mode": "words", "started": "2026-01-01T00:00:00Z",
                 "events": sorted(ev, key=lambda e: (e["t"], e["d"]))}]}, f)

    def test_cli_runs_and_reports_a_verdict(self):
        import subprocess
        import tempfile
        here = os.path.join(os.path.dirname(__file__), "..")
        with tempfile.TemporaryDirectory() as d:
            rec = os.path.join(d, "rec.json")
            self._recording(rec)
            for args in ([], ["--row", "home"], ["--compare"], ["--grid"]):
                out = subprocess.run(
                    [sys.executable, os.path.join(here, "analyze.py"), rec] + args,
                    capture_output=True, text=True)
                self.assertEqual(out.returncode, 0, f"{args}: {out.stderr}")
                self.assertTrue(out.stdout.strip(), f"{args}: no output")
            plain = subprocess.run(
                [sys.executable, os.path.join(here, "analyze.py"), rec],
                capture_output=True, text=True).stdout
            self.assertIn("RECOMMENDATION", plain)


if __name__ == "__main__":
    unittest.main(verbosity=2)
