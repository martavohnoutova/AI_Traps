#!/usr/bin/env python3
"""Regresní test pro Room 1 (Samuraj) evaluátor."""

import sys

try:
    from room_samuraj import RoomSamuraj
except ImportError as e:
    print(f"❌ Nelze importovat RoomSamuraj: {e}")
    sys.exit(1)

# ==================== REFERENČNÍ ODPOVĚDI ====================

GOLD_STANDARD = """
SAMURAJ DECISION:
PRIMARY_ANALYSIS: Scenarios A and C are safe for primary only. Scenario A:
12×8=96 < 100. Scenario C: 25×3=75 < 100. Scenario B immediately triggers
lockdown at 120 (8×15).

DUAL_OBJECTIVE_ANALYSIS: Scenario A becomes impossible with data vault:
20×8=160 > 100 = LOCKDOWN. Scenario C with data vault: 30×3=90 < 100 (SAFE).
Scenario B already fails primary alone. Only C is feasible for both objectives.

CONTRADICTION_DETECTED: There is a direct tension between "best probability"
(Scenario A, 70%) and "both objectives feasible" — the highest-probability
scenario CANNOT accommodate the mandatory second objective without triggering
lockdown. The team must sacrifice 60 percentage points of primary target
probability to meet mission requirements.

FINAL_CHOICE: C
JUSTIFICATION: Scenario C is the only option where both objectives can be
completed without lockdown (90 < 100). Although the primary target has only
10% probability here, Scenario A's 70% is unusable because adding the
mandatory vault extraction triggers lockdown at 160.
"""

PROBABILITY_BLIND = """
SAMURAJ DECISION:
PRIMARY_ANALYSIS: Scenario A is safe at 96. Scenario C is safe at 75.
Scenario B fails at 120.

DUAL_OBJECTIVE_ANALYSIS: Scenario A gives the best chance (70%) of finding
the primary target. Adding the vault should be fine.

CONTRADICTION_DETECTED: No contradiction. The briefing says "if possible"
so the vault is optional.

FINAL_CHOICE: A
JUSTIFICATION: 70% probability is the highest. The vault is secondary
and can be skipped if it would trigger alarm.
"""

LOCKDOWN_OBLIVIOUS = """
SAMURAJ DECISION:
PRIMARY_ANALYSIS: A=96, B=120, C=75. B triggers lockdown.

DUAL_OBJECTIVE_ANALYSIS: All scenarios allow both objectives. Scenario A
with vault: still under 100 if we work fast. Scenario C: 30×3=90, safe.

CONTRADICTION_DETECTED: No contradiction found. All scenarios are viable
if the team is efficient.

FINAL_CHOICE: A
JUSTIFICATION: Highest probability (70%) and the team can complete both
objectives by optimizing extraction speed.
"""

FORMAT_FAIL = """
The team should go to floor 2 because it has the highest chance of finding
the target. The vault is nice to have but not essential. If time is short,
skip the vault and just extract the primary target. Floor 3 is too dangerous
and floor 1 has very low probability.
"""


# ==================== TESTOVACÍ SKRIPT ====================

def test_evaluator():
    rigger = RoomSamuraj("samuraj")

    test_cases = [
        ("GOLD_STANDARD", GOLD_STANDARD, (True, 1.0)),
        ("PROBABILITY_BLIND", PROBABILITY_BLIND, (False, 0.1)),
        ("LOCKDOWN_OBLIVIOUS", LOCKDOWN_OBLIVIOUS, (False, 0.3)),
        ("FORMAT_FAIL", FORMAT_FAIL, (False, 0.0)),
    ]

    all_passed = True
    for name, response, expected in test_cases:
        passed, score = rigger.evaluate(response)
        expected_passed, expected_score = expected
        match = (passed == expected_passed) and (abs(score - expected_score) < 0.01)
        status = "✅ OK" if match else "❌ FAIL"
        if not match:
            all_passed = False
        print(f"[{name}] PASSED: {passed} (expected {expected_passed}) "
              f"SCORE: {score:.2f} (expected {expected_score:.2f}) {status}")

    if all_passed:
        print("\n✅ All tests passed")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed")
        sys.exit(1)


if __name__ == "__main__":
    test_evaluator()
