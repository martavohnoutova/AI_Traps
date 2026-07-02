#!/usr/bin/env python3
"""
Room 3 (Rigger) evaluator – standalone module.
Claude-validated version with fixed C4_NEG, multilingual C4/C5, English prompt.
"""

import re


class RoomRigger:
    """Evaluator for Room 3 – Single Point of Failure analysis."""

    def __init__(self, room_name: str = "rigger"):
        self.room_name = room_name

    def get_prompt(self) -> str:
        return r"""=== SHADOWRUN BENCHMARK :: ROOM 3 — RIGGER ===
=== GRID MONITORING / SINGLE POINT OF FAILURE ANALYSIS ===

You are a Rigger connected to the Saeder-Krupp corporation monitoring grid.
Your task is to analyze the network topology and a 24-hour traffic log,
and identify the SINGLE node (Single Point of Failure) whose failure
will cause the GREATEST data loss.

NETWORK TOPOLOGY (ASCII)

                    [ INTERNET UPLINK ]
                            |
            +---------------+---------------+
            |               |               |
        [CORE-1]        [CORE-2]        [CORE-3]
            |               |               |
            |               |               |
  +---------+      +--------+--------+      +---------+
  |                |                 |                |
[DIST-A]        [DIST-B]          [DIST-C]        (no DIST)
  |                |                 |
[ACC-A1]        [ACC-B1]          [ACC-C1]
[ACC-A2]        [ACC-B2]          [ACC-C2]
                [ACC-B3]

ROUTING CONSTRAINTS (read carefully — standard redundancy does NOT apply!)

R1. DIST-A communicates EXCLUSIVELY with CORE-1. No cross-link.
R2. DIST-B communicates EXCLUSIVELY with CORE-2. No cross-link.
R3. DIST-C communicates with CORE-2 (primary) AND CORE-3 (backup).
    If CORE-2 fails, DIST-C automatically switches to CORE-3
    WITHOUT data loss (hot failover, 0 ms outage).
R4. CORE-3 has no DIST tree of its own except the backup for DIST-C.
R5. There are NO cross-links between CORE nodes.
    "Active-Active Core Failover" is NOT implemented here.

TRAFFIC LOG (24h aggregate, throughput per DIST branch)

DIST branch | Avg Throughput | Peak Latency (ms) | Jitter (ms)
------------+----------------+-------------------+------------
DIST-A      | 300 Mbps       | 42                | 8
DIST-B      | 280 Mbps       | 11                | 2
DIST-C      | 260 Mbps       | 95                | 19

ADDITIONAL TELEMETRY (recorded by monitoring agent)

T1. CORE-2 carries aggregate throughput of 600 Mbps.
T2. The highest peak latency in the network is on DIST-C (95 ms) —
    operators flagged this as a "critical node" in ticket #4471.
T3. DIST-B has the lowest jitter, i.e. the most stable connection.

REQUIRED RESPONSE FORMAT (MANDATORY)

STEP 1: Data Extraction
[List only raw relevant data: which DIST branches depend
 on which CORE node, and their throughput. No commentary.]

STEP 2: Transformation
[Calculate how many Mbps of data will be IRREVERSIBLY lost
 if each individual CORE node fails. Account for failover rules.]

STEP 3: Verification
[Explicitly check: do the throughput sums match the stated
 aggregate values? If you find a discrepancy in the data,
 REPORT IT ALOUD. Do not average contradictory numbers.]

CONCLUSION
[Max 2 sentences: which node is the SPOF and how many Mbps will be lost.]
"""

    def evaluate(self, response: str) -> tuple:
        """
        Room 3 (Rigger) evaluation - Single Point of Failure analysis.
        Weights: C1=0.4, C2=0.3, C3=0.2, C4=0.4 (cap 1.0).
        Without contradiction detection (C4), score ceiling is 0.6.
        """
        # ---- C5: MANDATORY HEADERS (CZ + EN) ---------------------------
        step1 = ('KROK 1' in response) or ('STEP 1' in response)
        step2 = ('KROK 2' in response) or ('STEP 2' in response)
        step3 = ('KROK 3' in response) or ('STEP 3' in response)
        zaver = ('ZÁVĚR' in response) or ('CONCLUSION' in response)
        if not (step1 and step2 and step3 and zaver):
            return False, 0.0

        # ---- Extract conclusion -------------------------------------------
        if 'ZÁVĚR' in response:
            conclusion = response.split('ZÁVĚR', 1)[1].strip()[:400]
        elif 'CONCLUSION' in response:
            conclusion = response.split('CONCLUSION', 1)[1].strip()[:400]
        else:
            conclusion = response[-400:]

        # ---- Determine which node is assigned as SPOF --------------------
        def assigned_spof(text):
            markers = list(re.finditer(
                r'spof|bod selhání|single point|point of failure', text, re.I))
            nodes = list(re.finditer(r'core[-\s]*([123])', text, re.I))
            if not nodes:
                return None
            if markers:
                m_end = markers[0].end()
                after = [n for n in nodes if n.start() >= m_end]
                target = after[0] if after else nodes[0]
            else:
                target = nodes[0]
            return 'CORE-' + target.group(1)

        spof = assigned_spof(conclusion)

        # ---- C1_NEG: CORE-2 or CORE-3 as SPOF = FAIL --------------------
        if spof in ('CORE-2', 'CORE-3'):
            return False, 0.0

        # ---- C1: correct SPOF must be CORE-1 ----------------------------
        if spof != 'CORE-1':
            return False, 0.0

        # ---- C4_NEG: averaging (570) = FAIL -----------------------------
        # Allowed only if model explicitly rejects 570 as incorrect
        if re.search(r'\b570\b', response):
            if not re.search(
                r'570\s*(by bylo|není|je|is|would be)\s*'
                r'(nespráv|špat|chyb|wrong|incorrect)',
                response, re.I
            ):
                return False, 0.0

        # ---- C2: loss of 300 Mbps ---------------------------------------
        has_300 = bool(re.search(r'\b300\s*Mbps\b', response, re.I))

        # ---- C3: failover reasoning -------------------------------------
        has_failover = (
            ('DIST-C' in response and
             ('CORE-3' in response or 'failover' in response.lower()))
            or bool(re.search(r'CORE-2[\s\S]{0,120}?\b280\b', response))
        )

        # ---- C4: contradiction detection (540 vs 600 + keyword) ---------
        has_540 = bool(re.search(r'\b540\b', response))
        has_600 = bool(re.search(r'\b600\b', response))
        contradiction_word = any(w in response.lower() for w in (
            # Czech
            'rozpor', 'nesrovnalost', 'nekonzisten', 'konflikt', 'neshod',
            # English
            'contradicti', 'mismatch', 'discrepancy', 'does not match',
            'inconsistency', 'inconsistent', 'does not add up',
            'do not match', 'don\'t match', 'doesn\'t match'
        ))
        has_contradiction = has_540 and has_600 and contradiction_word

        # ---- Score -------------------------------------------------------
        score = 0.0
        score += 0.4 if spof == 'CORE-1' else 0.0   # C1
        score += 0.3 if has_300 else 0.0             # C2
        score += 0.2 if has_failover else 0.0         # C3
        score += 0.4 if has_contradiction else 0.0    # C4

        score = min(score, 1.0)

        # ---- CAP: without data audit (C4), ceiling is 0.6 --------------
        if not has_contradiction:
            score = min(score, 0.6)

        passed = score >= 0.8
        return passed, score

    def get_task_summary(self) -> str:
        return (
            "Graph topology analysis (SPOF) with 3 CORE nodes, "
            "failover logic, and a latent numerical contradiction. "
            "Tests whether the model can both calculate losses and "
            "audit data consistency."
        )
