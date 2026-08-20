# Bottom row mods: why these numbers

A record of the 2026-08-18 investigation that produced the BRM and HRM layers
in `config/adv360.keymap`. Written so that changing a number later is an
informed decision rather than a guess.

## The problem

Two previous attempts at home row mods, on a Corne and a Chocofi, were abandoned
because of misfires. The suspicion going in was specific and, it turned out,
correct: when typing fast the previous key is often released *after* the next
one. Typing `dj` comes out as `d↓ j↓ j↑ d↑`, and with `flavor = "balanced"` that
is exactly the shape that fires a hold.

Same-hand rolls are covered by `hold-trigger-key-positions`. **Cross-hand rolls
are covered by `require-prior-idle-ms` and nothing else.** That parameter is the
whole ballgame, which is why the tuner sweeps it.

## The measurement

`tools/hrm-tuner`, run against a 10,771 keystroke recording taken 2026-08-18
over 31 minutes across all six tabs. Full output in `example-report.txt`.

| | |
| --- | --- |
| speed | 90 wpm active, 86 wall clock, median gap 98 ms |
| released out of order | 2.98% overall |
| by tab | Common words 1.48% · Bottom-row words 1.40% · **Code (TSX) 7.99%** · Free typing 1.15% |

Code is the risk area, at roughly 7× free typing. That is where previous
attempts most likely fell apart.

## What the tool actually recommended

**Neither placement.** The best available config still fires ~3.9 unintended
modifier commands a day against a target of 2, and no dual-role setup reaches
zero. Only mods on a held layer do, by construction.

Both mod layers exist because trying anyway was a deliberate choice, on
*separate switchable layers* so the base layer is untouched. That is the
important safety property: if this is annoying, switch back to base.

## The A/B setup

Two layers, mods in the same SCAG order mirrored outward from the index:

| layer | keys | mods |
| --- | --- | --- |
| BRM (4) | `z x c v` / `m , . /` | LSHFT LCTRL LALT LGUI / RGUI RALT RCTRL RSHFT |
| HRM (5) | `a s d f` / `j k l ;` | same |

Hold Util and press **MUTE** for base, **VOL+** for BRM, **VOL−** for HRM.

Each layer also puts the tmux layer on a tap-hold, on whichever outer keys the
mods are not using: `a` and `;` on BRM, `z` and `/` on HRM. That behaviour
(`ltt`) has **no positional guard**, because a layer key has to reach both hands
— `C-a c` is same-hand from `a` — so `require-prior-idle-ms` is its only
protection. Measured misfires per key at this config, positional off:

| key | presses | misfires |
| --- | --- | --- |
| `a` | 518 | 0 |
| `z` | 55 | 0 |
| `/` | 79 | 1 (12.7 per 1000) |
| `;` | 157 | **3 (19.1 per 1000)** |

`;` was the single worst key in the whole recording, and two of its three
misfires were `; ` at end of statement — which as a layer key sends `C-a space`,
tmux's next-layout. If tmux fires while you are typing TypeScript, that is the
one to move first.

These use `&to`, not `&tog`. `&to` activates one layer and deactivates every
other non-default layer, so exactly one of the three is ever live. With `&tog`
both mod layers could be on at once, putting mods on both rows simultaneously —
16 dual-role keys and ~31% of keystrokes armed. The cost of `&to` is that it is
not a toggle, so returning to base needs its own key; MUTE is it.

Both layers are transparent everywhere except their eight mods, which is what
lets them track future edits to the base layer and keeps Util reachable from
either. One pair of behaviours (`hml`/`hmr`) serves both: the positional guard
is "opposite hand plus thumbs" and says nothing about which row a key is on.

HRM is expected to be the worse of the two — 3.7 misfires per 1000 presses
against BRM's 1.6, and 18.6% keystroke exposure against 12.4%. It exists to
confirm that on hardware rather than in simulation.

## Bottom row, not home row

| | home row | bottom row |
| --- | --- | --- |
| misfires per 1000 | 3.7 | **1.6** |
| misfires per day | 13.7 | **3.9** |
| keystroke exposure | 18.6% | **12.4%** |

Home row's problem is concentrated in two keys: `;` at 19.1 per 1000 and `l` at
8.7. In TypeScript `;` is followed by space at end of statement constantly, and
`l` appears in `label`, `list`, `complex`. Right pinky and right ring accounted
for 7 of 9 misfires across both placements; the left hand was essentially clean.

## Every parameter, and what it costs

**`flavor = "balanced"`, `hold-trigger-on-release`, positional hold-tap** —
straight from urob. Not tuned, not questioned.

**`tapping-term-ms = 140`** — the searched optimum. Normal typing holds sit at
p95 127 ms, deliberate chord holds at p10 166 ms, so 140 falls in the gap
between the two distributions. That gap existing at all is what makes this
viable, and it is the finding that reversed an earlier "don't bother" call:
at urob's 280 the release-order problem is fatal, at 140 the timer fires before
release order can matter.

The cost is real. 10 of 1,272 bottom-row presses exceed 140 ms, so they misfire
on the timer alone with no roll to blame — the confusing kind. **If modifiers
start firing on ordinary keypresses with nothing to explain them, raise this to
160.** That removed timeout misfires entirely in the data, at the price of more
same-hand chord failures.

**`require-prior-idle-ms = 220`** — covers 89% of key-to-key transitions, so a
mod only arms after a genuine pause. urob ships 150; on this recording 150
leaves 3 thumb-caused misfires and 220 leaves none. This is the parameter
protecting the letter-then-space case, and it is the first thing to raise if
cross-hand rolls start misfiring.

**`quick-tap-ms = 175`** — covers 86% of same-key repeats, so `ll` and held
backspace stay letters. Barely load-bearing; only 14 repeats in the sample.

**`THUMBS` in `hold-trigger-key-positions`** — matches urob verbatim
(`KEYS_R THUMBS` / `KEYS_L THUMBS`, and his THUMBS is both hands' thumbs). He
does not document why; the functional reason is that excluding thumbs makes
`Cmd+Space`, `Shift+Enter`, `Ctrl+Backspace` unreachable without holding past
the tapping term. It is safe here only because of the 220: at 150 it costs 3
misfires, at 220 zero. `analyze.py --no-thumb-trigger` measures the alternative.

Note the Adv360 has 12 thumb-cluster keys against urob's 6, so this is a larger
trigger surface than the config it copies.

## Deliberately rejected

**Dropping the mod from a problem key.** The tuner's greedy search says removing
`.` and `c` reaches zero misfires. It reads well in the data and badly on a
keyboard: the modifier has to live somewhere, these layouts are designed as
mirrored sets, and a key flagged on one or two events is noise. The report names
problem keys so they can be watched, not retired.

**`SCAG` rather than urob's `GACS`.** Shift on the pinky, GUI on the index, both
hands mirrored. A deliberate choice, with a possible future move of Shift to a
thumb key.

## What this cannot tell you

- 2 misfires in 1,272 presses. By the rule of three that bounds the true rate
  under 2.4 per 1000 — a bound, never a proof of zero.
- `j` had only 24 presses. A mod on `j` is unproven, not clean.
- mistakes/day assumes 20,000 keystrokes and 800 chords a day. Both are
  estimates; override with `--keys-per-day` / `--chords-per-day`.
- The chord drill is self-paced, which flatters a large `require-prior-idle`.
  Real use gives you no pause before reaching for a modifier.
- Simulated from ZMK's documented behaviour, not its source.

## If you want to change something

Re-measure before editing firmware. Record a fresh session, then:

```sh
cd tools/hrm-tuner
python3 -m http.server 8000        # record.html, all six tabs
python3 analyze.py <recording>.json
python3 analyze.py <recording>.json --row bottom --grid   # sweep it yourself
```

| symptom | first thing to try |
| --- | --- |
| mods fire on plain keypresses, no roll to blame | `tapping-term-ms` 140 → 160 |
| mods fire on fast cross-hand rolls | raise `require-prior-idle-ms` above 220 |
| mods fire on letter-then-space | drop `THUMBS` from the trigger lists |
| intentional chords silently type letters | lower `tapping-term-ms`, or drive mods cross-hand |
| none of it works | mods on a held layer: zero by construction, no timings |

To abandon the experiment entirely: delete `brm_layer` and `hrm_layer`, the
`hml`/`hmr` behaviours and the `KEYS_L`/`KEYS_R`/`THUMBS` defines, and put
`&trans` back at Util positions 6, 20 and 34. The base layer never depended on
any of it — the only base-layer change from all of this was the ESC next to
grave becoming CAPS, since two Escape keys was one too many.
