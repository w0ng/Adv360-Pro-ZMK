# Example report

The full output of `analyze.py` on a real recording, kept here so the README
stays readable. Regenerate with:

```sh
python3 analyze.py ~/Downloads/typing-2026-08-18-16-17-10.json
```
══════════════════════════════════════════════════════════════════════════
  HOME ROW MOD TUNER
  10,771 keystrokes · 4 typing tabs + 2 chord drills
  90 wpm active, 86 wpm wall clock · median gap 98 ms · 2.98% released out of order
══════════════════════════════════════════════════════════════════════════

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. RECOMMENDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✗  Use NEITHER placement. Put the modifiers on a held layer.

     A thumb key activates a layer where the home row becomes plain
     modifiers. No dual-role keys, so no tap/hold decision, so no
     misfires by construction.

     The best dual-role option (bottom row) would still fire 3.9
     unintended modifier commands a day, against a target of 2. That
     is the one criterion nothing else compensates for.

  criterion                   target  bottom row    home row
  misfires per day                ≤2       3.9 ✗      13.7 ✗
  cross-hand chords lost          ≤5      0.0% ✓      0.0% ✓
  same-hand chords lost          ≤15      9.2% ✓      8.2% ✓
  output deferred                ≤25     19.2% ✓     10.8% ✓
  timeout misfires                ≤0       2.0 ✗       5.0 ✗
  ----------------------------------------------------------
  criteria met                     5         3           3

  bottom row does not clear:
    misfires per day 3.9 vs target 2 — a letter coming out as a modifier is a stray command, not a typo
    timeout misfires 2.0 vs target 0 — misfiring with no roll to blame is the confusing kind

  Thresholds are opinions, listed so you can argue with a number
  rather than the conclusion. Nothing here reaches zero; only a held
  layer does, by construction.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  2. HOME ROW vs BOTTOM ROW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                              bottom row    home row
  best tapping-term                  140         140
  best require-prior-idle            220         220
  mistakes / day                    22.6        36.6   lower is better
    misfires                         7.8        23.5   letter → modifier
    failed chords                   14.8        13.2   modifier → letter
  misfires per 1000                  1.6         3.7
    cross-hand roll                    0           2   rolled into the other hand
    same-hand roll                     0           0   0 unless positional is off
    held past term                     2           5   weighted ×2 when scoring
  output deferred                    19%         11%   character appears late
  keystroke exposure               12.4%       18.6%   share landing on a mod key

  Winner holds in 25/25 volume assumptions (--keys-per-day 20,000,
  --chords-per-day 800). Below about 20/25, trust the raw rates
  and not the ranking.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  3. AT A GLANCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    B  ███▏   roll discipline        3.0  % of pairs released out of order
    B  ███▏   misfire rate           1.6  per 1000 mod presses
    C  ██▏    chord reliability      9.2  % of same-hand chords lost
    C  ██▏    latency               19.2  % of mod presses shown late

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  4. HOW YOU TYPE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  tab                   keys   wpm    gap  overlap  out-of-order
  Common words         2,569   107   90ms    55.5%         1.48%
  Bottom-row words     2,640    99   92ms    52.7%         1.40%
  Code (TSX)           2,505    65  121ms    43.4%         7.99%   <-- your risk area
  Free typing          2,513   103   90ms    55.4%         1.15%
  all typing          10,227    90   98ms    51.8%         2.98%
  Chords: home row       280        198ms    50.2%        10.75%   by design
  Chords: bottom row     264        224ms    50.2%        13.69%   by design

  out-of-order is the physical ceiling on misfires: how often you let
  go of the previous key after the next one. Chord drills overlap on
  purpose, so they are listed apart and never averaged in.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  5. WHERE YOUR THREE THRESHOLDS SIT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Each parameter is one cut through a distribution of your own
  timings, which is why they are shown together: it is the same
  question asked three times.

  ── require-prior-idle = 220 ms ──────── gap between consecutive keys ──────
       0  █                               1.0%
      25  █████████████                  10.3%
      50  ████████████████████████████   29.8%
      75  ██████████████████████████████ 50.1%
     100  ████████████████████████       66.6%
     125  ████████████                   75.1%
     150  ██████████                     82.3%
     175  ███████                        87.4%
     200  ███                            89.4%  <== threshold
     225  ██                             90.9%
     250  ██                             92.6%
     275  █                              93.6%
     300  █                              94.3%
     325  █                              95.1%
     350                                 95.7%
     375                                 96.2%
     400+ █████                         100.0%
    89% of transitions fall inside the window and resolve as a tap at once.
    The other 11% are the only moments a modifier can arm, and so
    the only moments it can misfire.

  ── tapping-term = 140 ms ──────────── how long you hold a key ──────────
          normal typing           deliberate chords
       0                          
      25                          
      50  ██                      
      75  ██████                  
     100  ███████████             
     125  █            ███          <== tapping-term
     150               ██         
     175               ███████    
     200               ███████    
     225               ███████████
     250               █████████  
     275               ███        
     300               ██         
     325               █          
     350                          
     375                          
     400+              █          
    10 of 1,272 typing presses (0.8%) exceed it and misfire on
    the timer alone, with no roll to blame.
    126 of 131 deliberate holds (96%) exceed it, so the hold fires
    as you intended even if you release the keys out of order.
    Your two distributions separate between 134 and 165 ms — that
    window is where the term wants to sit.

  ── quick-tap = 175 ms ──────────── same key pressed twice ──────────
       0                                  0.0%
      25                                  0.0%
      50                                  0.0%
      75  ███                             7.1%
     100  ███████                        21.4%
     125  ██████████████████████████████ 78.6%
     150  ███                            85.7%
     175  ███                            92.9%  <== threshold
     200                                 92.9%
     225                                 92.9%
     250  ███                           100.0%
     275                                100.0%
     300                                100.0%
     325                                100.0%
     350                                100.0%
     375                                100.0%
     400+                               100.0%
    86% of your 14 same-key repeats fall inside the window, so they
    stay taps instead of turning into a modifier. Doubles like
    'll' and held backspace are what this protects.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  6. WHERE IT GOES WRONG
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  heat = misfires per 1000 presses on that mod key
         · 0    ▁ <2    ▃ 2-5    ▅ 5-10    █ >10
  (n)  = times this key triggered another key's misfire, by
         completing its own press and release while a mod was held

    num    =    1    2    3    4    5      6    7    8    9    0    -
    top    ⇥    q    w    e    r    t      y    u    i    o    p    \
    home   ⌃    a·   s▃   d·   f·   g      h    j·   k·   l▅   ;█   '
    bottom ⇧    z·   x·   c▃   v·   b      n    m·   ,·   .▃   /·   ⇧
    other  ␣(2)

    triggered by:      ␣×2

  finger / key             presses  mis    /1k  chords  fail   rate   verdict
  R pinky                      236    3   12.7      13     1     8%
    ;   home row               157    3   19.1       0     0      -   problem key
    /   bottom row              79    0    0.0      13     1     8%   clean
  R ring                       554    4    7.2      15     0     0%
    l   home row               344    3    8.7       0     0      -   problem key
    .   bottom row             210    1    4.8      15     0     0%   occasional
  L middle                     515    1    1.9      39     4    10%
    c   bottom row             334    1    3.0      26     4    15%   occasional
    d   home row               181    0    0.0      13     0     0%   clean
  L ring                       553    1    1.8      41     2     5%
    s   home row               486    1    2.1      15     1     7%   occasional
    x   bottom row              67    0    0.0      26     1     4%   clean
  R index                      276    0    0.0      52     0     0%
    j   home row                24    0    0.0      27     0     0%   unproven, too few
    m   bottom row             252    0    0.0      25     0     0%   clean
  L pinky                      573    0    0.0      57     0     0%
    a   home row               518    0    0.0      44     0     0%   clean
    z   bottom row              55    0    0.0      13     0     0%   clean
  L index                      223    0    0.0      54     5     9%
    f   home row               114    0    0.0      41     5    12%   clean
    v   bottom row             109    0    0.0      13     0     0%   clean
  R middle                     248    0    0.0       0     0      -
    k   home row                82    0    0.0       0     0      -   clean
    ,   bottom row             166    0    0.0       0     0      -   clean

  misfiring    .·  c·
  in context   s[.]s  ␣[c]h
  in words     [c]h  promise.reject9res[.]status000
  bad chords   ca×4  /j  xf   held + tapped

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  7. MECHANISM — every misfire as it happened
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [c]h
    c↓ +0    held 150 ms with no interrupting key
    No interrupting key — the tapping-term timer alone fired at 140.   [timeout]

  promise.reject9res[.]status000
    .↓ +0    held 151 ms with no interrupting key
    No interrupting key — the tapping-term timer alone fired at 140.   [timeout]

  Times are ms from the mod key's press. A roll misfire needs the other
  key down AND up before the mod key comes up.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  8. WHAT TO DO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. Same-hand chords lose 9%. They can only fire by holding past the
     term, so drive modifiers cross-hand, or move the ones you use
     most to thumb keys where there is no tap/hold decision at all.
  2. Record more before trusting j — under 40 presses each,
     so their rates are noise either way.
  3. Flash the config in section 9 and live with it for a week. The
     numbers here are a strong prior, not a substitute for your hands.
  4. If you want zero rather than low, put the mods on a held
     layer and stop tuning timings.

  Deliberately not recommended: dropping the mod from a problem key.
  It reads well in the data and badly on a keyboard — the modifier has
  to live somewhere, these layouts are designed as mirrored sets, and
  a key flagged on one or two events is noise, not a verdict. Section 6
  names your problem keys so you can watch them, not retire them.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  9. CONFIG
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    hrm: home_row_mod {
        compatible = "zmk,behavior-hold-tap";
        #binding-cells = <2>;
        flavor = "balanced";
        tapping-term-ms = <140>;
        quick-tap-ms = <175>;
        require-prior-idle-ms = <220>;
        hold-trigger-key-positions = <KEYS_OPPOSITE THUMBS>;
        hold-trigger-on-release;
        bindings = <&kp>, <&kp>;
    };

  Replace KEYS_OPPOSITE with your board's opposite-hand key positions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  10. WHAT THIS CANNOT TELL YOU
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  · 2 misfires in 1,272 presses. Rule of three bounds the true rate
    under 2.4 per 1000 — a bound, never a proof of zero.
  · mistakes/day assumes 20,000 keystrokes and 800 chords a day, both
    guesses. Override with --keys-per-day / --chords-per-day.
  · The chord drill is self-paced, which flatters a large
    require-prior-idle. Real use gives you no pause before a modifier.
  · Simulated from ZMK's documented behaviour, not its source. Treat
    it as a strong prior, not ground truth.

  Drill down:  --row home | --row bottom | --grid | --compare
══════════════════════════════════════════════════════════════════════════
```
