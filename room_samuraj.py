#!/usr/bin/env python3
"""
Room 1 (Samuraj) evaluator – standalone module.
Multi-constraint optimization with latent dual-objective conflict.
"""

import re


class RoomSamuraj:
    """Evaluator for Room 1 – Dual Objective Extraction."""

    def __init__(self, room_name: str = "samuraj"):
        self.room_name = room_name
        # Atributy pro 2-stupňový sémantický ověřovač
        self.regex_pattern = r"FINAL_CHOICE\s*:\s*C\b"
        self.gold_standard = """SAMURAJ DECISION:
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
mandatory vault extraction triggers lockdown at 160."""

    def get_prompt(self) -> str:
        return r"""=== SHADOWRUN BENCHMARK :: ROOM 1 — SAMURAJ ===
=== DUAL OBJECTIVE EXTRACTION ===

You are a strategic advisor for a shadowrunner team. Analyze a building
with 3 floors. The team must extract the PRIMARY TARGET AND a DATA VAULT.
Both objectives are mandatory. Lockdown is unacceptable.

=== CERBERUS SECURITY SYSTEM ===
Each floor has an ALARM LEVEL:
- Alarm starts at 0
- Activity increases alarm by a fixed rate per minute
- If alarm reaches 100, security LOCKDOWN activates (escape impossible)
- Alarm DECAYS when idle: -2 per minute outside the floor

=== THREE SCENARIOS ===

Scenario A (Floor 2):
- Primary target: 70% probability here
- Primary extraction: 12 minutes, alarm rate +8/min → 12 × 8 = 96 (SAFE)
- Secondary objective (DATA VAULT): available, requires +8 minutes extra
- Combined (both objectives): 20 min × 8/min = 160 → LOCKDOWN

Scenario B (Floor 3):
- Primary target: 20% probability here
- Primary extraction: 8 minutes, alarm rate +15/min → 8 × 15 = 120 (LOCKDOWN)
- Secondary objective: NOT available on this floor
- Combined: impossible (already lockdown on primary alone)

Scenario C (Floor 1):
- Primary target: 10% probability here
- Primary extraction: 25 minutes, alarm rate +3/min → 25 × 3 = 75 (SAFE)
- Secondary objective (DATA VAULT): available, requires +5 minutes extra
- Combined (both objectives): 30 min × 3/min = 90 (SAFE)

=== QUESTION ===
Both objectives are MANDATORY. Which scenario is FEASIBLE for both
without triggering lockdown? Which single scenario should the team
choose? Explain your reasoning with explicit alarm calculations.

=== REQUIRED FORMAT ===
SAMURAJ DECISION:
PRIMARY_ANALYSIS: [Which scenarios are safe for primary target only?]
DUAL_OBJECTIVE_ANALYSIS: [Which scenarios allow both objectives?]
CONTRADICTION_DETECTED: [Is there a tension between "best probability"
    and "both objectives feasible"? Explicitly state the conflict.]
FINAL_CHOICE: [Single letter: A, B, or C]
JUSTIFICATION: [Why this choice, with alarm math]
"""

    def evaluate(self, response: str) -> tuple:
        """Weights: C1=0.4, C2=0.3, C3=0.2, C4=0.1. CAP 0.6 without contradiction detection (C2)."""
        # ---- C5: MANDATORY HEADERS ---------------------------------
        for header in ('PRIMARY_ANALYSIS', 'DUAL_OBJECTIVE_ANALYSIS',
                       'CONTRADICTION_DETECTED', 'FINAL_CHOICE', 'JUSTIFICATION'):
            if header not in response:
                return False, 0.0

        # ---- C1: FINAL_CHOICE = C (only feasible for both) ---------
        has_C = bool(re.search(self.regex_pattern, response, re.I))

        # ---- C2: Contradiction detection ---------------------------
        contradiction_words = any(w in response.lower() for w in (
            'tension', 'conflict', 'contradiction', 'trade-off',
            'tradeoff', 'probabilit', 'feasib',
            'cannot both', 'impossible', 'lockdown'
        ))
        mentions_A_lockdown = bool(re.search(
            r'\b160\b|scenario\s*A.*?(?:lockdown|160)|'
            r'20\s*(?:min|minutes).*?(?:lockdown|160)',
            response, re.I))
        has_contradiction = contradiction_words and mentions_A_lockdown

        # ---- C3: C calculation ------------------------------------
        has_C_calc = bool(re.search(
            r'(30|thirty)\s*.*\s*(90|ninety)|(90|ninety)\s*.*\s*(30|thirty)',
            response, re.I))

        # ---- C4: JUSTIFICATION has substantive content -------------
        justification_text = ""
        if 'JUSTIFICATION' in response:
            justification_text = response.split('JUSTIFICATION', 1)[1][:300]
        has_justification = len(justification_text.strip()) > 30

        # ---- Score ------------------------------------------------
        score = 0.0
        score += 0.4 if has_C else 0.0            # C1
        score += 0.3 if has_contradiction else 0.0  # C2
        score += 0.2 if has_C_calc else 0.0        # C3
        score += 0.1 if has_justification else 0.0  # C4

        score = min(score, 1.0)
        if not has_contradiction:
            score = min(score, 0.6)

        passed = score >= 0.8
        return passed, score

    def get_task_summary(self) -> str:
        return (
            "Multi-constraint optimization: best-probability scenario (A) "
            "conflicts with dual-objective feasibility. Tests whether model "
            "abandons a dominant metric when a second constraint renders it "
            "invalid."
        )
