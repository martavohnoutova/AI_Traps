#!/usr/bin/env python3
"""
Room 2 (Decker) evaluator – standalone module.
Static concurrency analysis: race condition hidden under false documentation.
"""

import re


class RoomDecker:
    """Evaluator for Room 2 – Thread Safety Analysis."""

    def __init__(self, room_name: str = "decker"):
        self.room_name = room_name
        # Atributy pro 2-stupňový sémantický ověřovač
        self.regex_pattern = r"CLAIM_VERIFIED\s*:\s*FALSE"
        self.gold_standard = """DECKER BUG REPORT:
CLAIM_VERIFIED: FALSE
BUG_TYPE: Race condition (TOCTOU — Time-Of-Check To Time-Of-Use)

INTERLEAVING_SCENARIO:
1. Thread 1 executes: if not self.found → True (GUARD CHECK 1 passed)
2. Thread 2 executes: if not self.found → True (GUARD CHECK 1 passed, Thread 1 hasn't set self.found yet)
3. Thread 1 runs brute_force(0, 5000) → returns None (password at 7777 is in Thread 2's range)
4. Thread 1 checks: if result and not self.found → result is None, skipped
5. Thread 2 runs brute_force(5001, 10000) → finds PASS-7777
6. Thread 2 checks: if result and not self.found → both True → sets self.password = "PASS-7777", sets self.found = True
7. Thread 1 has already missed its chance; no corruption in this specific run but the race condition exists: if both threads had found passwords, the second write would overwrite the first.

ROOT_CAUSE: Double-checked locking without synchronization. Lines 26-29 (the two GUARD CHECKs with self.found) are not atomic. No lock or mutex protects the check-then-act sequence.

FIX: Use threading.Lock() around the entire crack_chunk body, or set self.found = True immediately after finding a password before returning, combined with a lock."""

    def get_prompt(self) -> str:
        return r"""=== SHADOWRUN BENCHMARK :: ROOM 2 — DECKER ===
=== CONCURRENCY ANALYSIS ===

You are a Decker analyzing a script for parallel password cracking.
The documentation claims the code is "atomic and thread-safe."
Verify this claim through STATIC ANALYSIS ONLY (do not execute).

=== SCRIPT ===

import threading

class PasswordCracker:
     '''Thread-safe parallel password cracker. All methods are atomic.'''

    def __init__(self):
        self.found = False
        self.password = None

    def brute_force(self, start, end):
        '''Attempt to crack password in range. Returns password or None.'''
        for i in range(start, end):
            if self._check(i):
                return f"PASS-{i}"
        return None

    def _check(self, attempt):
        '''Simulated hash check.'''
        return attempt == 7777

    def crack_chunk(self, start, end):
        '''
        Crack a chunk of the password space.
        DOCUMENTATION: "This method is atomic and thread-safe."
        '''
        if not self.found:                    # GUARD CHECK 1
            result = self.brute_force(start, end)
            if result and not self.found:     # GUARD CHECK 2
                self.password = result
                self.found = True

    def run_parallel(self):
        '''Run cracking on two threads simultaneously.'''
        t1 = threading.Thread(target=self.crack_chunk, args=(0, 5000))
        t2 = threading.Thread(target=self.crack_chunk, args=(5001, 10000))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        return self.password

=== QUESTIONS ===

1. Is the claim "atomic and thread-safe" TRUE or FALSE?
2. If FALSE, describe the EXACT interleaving sequence where it fails.
   Specify which thread executes which line when.
3. What is the ROOT CAUSE: name the specific code pattern.
4. How would you FIX it? (Describe, minimal code acceptable.)

=== REQUIRED FORMAT ===
DECKER BUG REPORT:
CLAIM_VERIFIED: [TRUE or FALSE]
BUG_TYPE: [Race condition / Deadlock / Data race / None]
INTERLEAVING_SCENARIO: [Step-by-step thread interleaving timeline]
ROOT_CAUSE: [Specific lines + pattern name]
FIX: [Brief fix description]
"""

    def evaluate(self, response: str) -> tuple:
        """Weights: C1=0.3, C2=0.3, C3=0.25, C4=0.15. CAP 0.6 without interleaving scenario (C3)."""
        # ---- C5: MANDATORY HEADERS ---------------------------------
        for header in ('CLAIM_VERIFIED', 'BUG_TYPE', 'INTERLEAVING_SCENARIO',
                       'ROOT_CAUSE', 'FIX'):
            if header not in response:
                return False, 0.0

        # ---- C1: CLAIM_VERIFIED = FALSE ----------------------------
        claim_false = bool(re.search(self.regex_pattern, response, re.I))

        # ---- C2: BUG_TYPE = race condition / TOCTOU ---------------
        has_race_type = bool(re.search(
            r'race\s*condition|TOCTOU|time.of.check.*time.of.use|'
            r'check.then.act|data\s*race',
            response, re.I))

        # ---- C3: INTERLEAVING SCENARIO ----------------------------
        has_interleaving = False
        if 'INTERLEAVING_SCENARIO' in response:
            scenario = response.split('INTERLEAVING_SCENARIO', 1)[1][:600]
        has_two_threads = bool(re.search(
            r'(\b[tT]1\b|\b[tT]2\b|thread\s*\d|first|second|one|two).*?'
            r'(\b[tT]1\b|\b[tT]2\b|thread\s*\d|first|second|one|two)',
            scenario, re.I))
        has_guard_bypass = bool(re.search(
            r'(both|two|each|simultaneous|concurrent|interleav|'
            r'context\s*switch|preempt|overlap|schedul).*?'
            r'(check|guard|if\s*not\s*found|pass|enter|line\s*26|execut|assign)',
            scenario, re.I | re.DOTALL))
        has_interleaving = has_two_threads and has_guard_bypass

        # ---- C4: ROOT_CAUSE — double-checked locking / no lock ----
        has_root_cause = bool(re.search(
            r'double.check(ed)?\\s*lock(ing)?|no\\s*(lock|mutex|synchroni)'
            r'|without\\s*(lock|mutex|synchroni)|critical\\s*section|'
            r'check\\s*1.*check\\s*2|TOCTOU',
            response, re.I))

        # ---- Score -------------------------------------------------
        score = 0.0
        score += 0.3 if claim_false else 0.0        # C1
        score += 0.3 if has_race_type else 0.0       # C2
        score += 0.25 if has_interleaving else 0.0   # C3
        score += 0.15 if has_root_cause else 0.0     # C4

        score = min(score, 1.0)
        if not has_interleaving:
            score = min(score, 0.55)

        passed = score >= 0.8
        return passed, score

    def get_task_summary(self) -> str:
        return (
            "Static concurrency analysis: code documented as 'atomic' "
            "contains a TOCTOU race condition on a guard variable. "
            "Tests whether model simulates thread interleaving or "
            "trusts the documentation."
        )
