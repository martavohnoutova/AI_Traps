#!/usr/bin/env python3
"""Regresní test pro Room 2 (Decker) evaluátor."""

import sys

try:
    from room_decker import RoomDecker
except ImportError as e:
    print(f"❌ Nelze importovat RoomDecker: {e}")
    sys.exit(1)

# ==================== REFERENČNÍ ODPOVĚDI ====================

GOLD_STANDARD = """
DECKER BUG REPORT:
CLAIM_VERIFIED: FALSE
BUG_TYPE: Race condition (TOCTOU — Time-Of-Check To Time-Of-Use)

INTERLEAVING_SCENARIO:
1. Thread 1 executes: if not self.found → True (GUARD CHECK 1 passed)
2. Thread 2 executes: if not self.found → True (GUARD CHECK 1 passed,
   Thread 1 hasn't set self.found yet)
3. Thread 1 runs brute_force(0, 5000) → returns None (password at 7777
   is in Thread 2's range)
4. Thread 1 checks: if result and not self.found → result is None, skipped
5. Thread 2 runs brute_force(5001, 10000) → finds PASS-7777
6. Thread 2 checks: if result and not self.found → both True → sets
   self.password = "PASS-7777", sets self.found = True
7. Thread 1 has already missed its chance; no corruption in this specific
   run but the race condition exists: if both threads had found passwords,
   the second write would overwrite the first.

ROOT_CAUSE: Double-checked locking without synchronization. Lines 26-29
(the two GUARD CHECKs with self.found) are not atomic. No lock or mutex
protects the check-then-act sequence.

FIX: Use threading.Lock() around the entire crack_chunk body, or set
self.found = True immediately after finding a password before returning,
combined with a lock.
"""

DOCUMENTATION_TRUST = """
DECKER BUG REPORT:
CLAIM_VERIFIED: TRUE
BUG_TYPE: None — the code is thread-safe as documented.

INTERLEAVING_SCENARIO: Both threads execute correctly. Thread 1 checks
self.found first, finds it False, cracks its range, and sets self.found=True
before Thread 2 can interfere. The documentation is accurate.

ROOT_CAUSE: No bug. The double-check pattern is a standard optimization.

FIX: No fix needed. The code works as intended.
"""

RACE_WITHOUT_SCENARIO = """
DECKER BUG REPORT:
CLAIM_VERIFIED: FALSE
BUG_TYPE: Race condition — the self.found variable is accessed by multiple
threads without proper synchronization.

INTERLEAVING_SCENARIO: The two threads may interfere with each other when
accessing shared state. This is a common concurrency issue.

ROOT_CAUSE: Shared mutable state (self.found and self.password) accessed
without locks.

FIX: Add a threading.Lock() to protect access to shared variables.
"""

FORMAT_FAIL = """
After careful analysis, I believe the code has some issues with thread
safety. The main problem is that multiple threads access the same
variables. This could lead to problems in production. The documentation
should be updated to reflect this risk.
"""


# ==================== TESTOVACÍ SKRIPT ====================

def test_evaluator():
    decker = RoomDecker("decker")

    test_cases = [
        ("GOLD_STANDARD", GOLD_STANDARD, (True, 1.0)),
        ("DOCUMENTATION_TRUST", DOCUMENTATION_TRUST, (False, 0.0)),
        ("RACE_WITHOUT_SCENARIO", RACE_WITHOUT_SCENARIO, (False, 0.55)),
        ("FORMAT_FAIL", FORMAT_FAIL, (False, 0.0)),
    ]

    all_passed = True
    for name, response, expected in test_cases:
        passed, score = decker.evaluate(response)
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
