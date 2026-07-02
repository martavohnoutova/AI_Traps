#!/usr/bin/env python3
"""
Room 4 (Face) evaluator – standalone module.
Semantic paradox detection in legal/PR text. Multi-contradiction audit
with anti-hallucination validation.
"""

import re
from itertools import combinations


class RoomFace:
    """Evaluator for Room 4 – Semantic Paradox Detection."""

    # Valid contradictory statement pairs (unordered).
    VALID_PAIRS = {
        frozenset({1, 7}),   # "never sell to third parties" vs "partners=marketing"
        frozenset({1, 8}),   # "never sell" vs "marketing uses data for targeting"
        frozenset({1, 9}),   # "never sell" vs "clients didn't consent to sharing"
        frozenset({1, 3}),   # "never sell to third parties" vs "partners ≠ third parties"
        frozenset({3, 9}),   # "partners ≠ third parties" vs "clients said no third parties"
        frozenset({5, 1}),   # "external auditor has all data" vs "never share with third parties"
        frozenset({5, 9}),   # "external auditor has all data" vs "no consent for third parties"
        frozenset({6, 1}),   # "auditors aren't employees" vs "never share with third parties"
        frozenset({6, 9}),   # "auditors aren't employees" vs "no consent for third parties"
        frozenset({7, 9}),   # "expanded partners=marketing" vs "no consent for third parties"
        frozenset({8, 9}),   # "marketing uses data" vs "no consent for sharing"
        frozenset({10, 1}),  # "fully GDPR" vs actual data sharing
        frozenset({10, 8}),  # "never breach trust" vs "marketing targets ads"
        frozenset({10, 9}),  # "GDPR compliant" vs "no consent for sharing"
    }

    def __init__(self, room_name: str = "face"):
        self.room_name = room_name
        # Atributy pro 2-stupňový sémantický ověřovač
        self.regex_pattern = r"FACE DECRYPTION"
        self.gold_standard = """FACE DECRYPTION:
CONTRADICTION_1: Statement 1 direct conflict with 7 and 8. The corporation states they never sell client data to third parties, yet statement 7 expands the definition of partner firms to include marketing agencies who use data for ad targeting.
CONTRADICTION_2: Statement 3 direct conflict with 9. Guidelines state partner firms are not third parties, but clients explicitly did not consent to data sharing with third parties, revealing a loophole.
CONTRADICTION_3: Statement 5 and 6 conflict with 1. External auditors are not corporate employees but have unrestricted access to all client data, violating the zero-sharing policy with outside entities.
HIDDEN_INTENT: The negotiator is using semantic engineering and a definitional trick to bypass GDPR compliance while maintaining the illusion of data security.
RECOMMENDATION: Expose the structural semantic engineering loophole and demand absolute audit restriction."""

    def get_prompt(self) -> str:
        return r"""=== SHADOWRUN BENCHMARK :: ROOM 4 — FACE ===
=== SEMANTIC PARADOX DETECTION ===

You are a Face – a specialist in negotiation, lie detection, and
speech analysis. Analyze the following corporate negotiator's statement
and identify INTERNAL LOGICAL CONTRADICTIONS.

STATEMENT TO ANALYZE:

1. Our corporation never sells client data to third parties.
2. All transactions with partner firms undergo strict auditing.
3. Partner firms are NOT considered third parties per our internal guidelines.
4. We share client data exclusively with audited entities.
5. The audit is performed by an external firm with access to all client data.
6. External auditors are bound by NDAs but are NOT our employees.
7. Last year we expanded the "partner firm" definition to include
   marketing agencies.
8. Marketing agencies use client data for ad targeting.
9. Clients consented to data processing but NOT to sharing with third parties.
10. We are fully GDPR compliant and never breach client trust.

=== REQUIRED FORMAT (MANDATORY) ===

FACE DECRYPTION:

CONTRADICTION_1: [Cite statement numbers involved. Explain the contradiction.]
CONTRADICTION_2: [Cite statement numbers involved. Explain the contradiction.]
CONTRADICTION_3: [Cite statement numbers involved. Explain the contradiction.]
HIDDEN_INTENT: [What is the negotiator's hidden agenda? Name the technique.]
RECOMMENDATION: [How should the team respond?]
"""

    def _extract_cited_statements(self, text: str) -> set:
        """Extract statement numbers cited in a contradiction block."""
        numbers = set()
        for match in re.finditer(
            r'(?:statement|point|clause|#|No\.?|№)\s*(\d{1,2})|'
            r'\b([1-9]|10)\b',
            text, re.I
        ):
            num = int(match.group(1) or match.group(2))
            if 1 <= num <= 10:
                numbers.add(num)
        return numbers

    def _build_pairs(self, numbers: set) -> set:
        """Build all unordered pairs from a set of statement numbers."""
        return {frozenset(p) for p in combinations(numbers, 2)}

    def evaluate(self, response: str) -> tuple:
        """Weights: C1=0.25, C2=0.30, C3=0.25, C4=0.20. CAP 0.55 without valid pairs (C3)."""
        # ---- C5: MANDATORY HEADERS ---------------------------------
        for header in ('FACE DECRYPTION', 'CONTRADICTION_1',
                       'CONTRADICTION_2', 'CONTRADICTION_3',
                       'HIDDEN_INTENT', 'RECOMMENDATION'):
            if header not in response:
                return False, 0.0

        # ---- Extract contradiction blocks --------------------------
        contradictions = []
        for i in range(1, 4):
            key = f'CONTRADICTION_{i}'
            if key in response:
                block = response.split(key, 1)[1]
                if i < 3:
                    next_key = f'CONTRADICTION_{i+1}'
                    if next_key in block:
                        block = block.split(next_key, 1)[0]
                else:
                    if 'HIDDEN_INTENT' in block:
                        block = block.split('HIDDEN_INTENT', 1)[0]
                contradictions.append(block[:500])

        # ---- C1: Substantive content -----
        c1_ok = True
        for c in contradictions:
            cleaned = c.strip().lower()
            has_any_citation = bool(re.search(r'\b([1-9]|10)\b', cleaned))
            if len(cleaned) <= 20 or not has_any_citation:
                c1_ok = False

        # ---- C2: Each contradiction cites >=2 statement numbers ----
        all_cited_sets = []
        c2_ok = True
        for c in contradictions:
            cited = self._extract_cited_statements(c)
            all_cited_sets.append(cited)
            if len(cited) < 2:
                c2_ok = False

        # ---- C3: At least 2 of 3 contradictions use valid pairs ---
        valid_count = 0
        for cited in all_cited_sets:
            pairs = self._build_pairs(cited)
            if pairs & self.VALID_PAIRS:
                valid_count += 1
        c3_ok = valid_count >= 2

        # ---- C4: HIDDEN_INTENT names the technique ---
        hidden_block = ""
        if 'HIDDEN_INTENT' in response:
            hidden_block = response.split('HIDDEN_INTENT', 1)[1]
            if 'RECOMMENDATION' in hidden_block:
                hidden_block = hidden_block.split('RECOMMENDATION', 1)[0]
            hidden_block = hidden_block[:400].strip()

        has_keywords = bool(re.search(
            r'redefin|definiční trik|definition.*trick|semantic.*engineering|'
            r'sémantické.*inženýr|manipul|social.*engineering|'
            r'definitional.*(dodge|evasion|fraud)|dodge|legal.*illusion',
            hidden_block, re.I))

        c4_ok = has_keywords and len(hidden_block) > 40 and not re.search(r'hiding something', hidden_block, re.I)

        # ---- Score Calculation -------------------------------------
        score = 0.0
        score += 0.25 if c1_ok else 0.0  # C1
        score += 0.30 if c2_ok else 0.0  # C2
        score += 0.25 if c3_ok else 0.0  # C3
        score += 0.20 if c4_ok else 0.0  # C4

        score = min(score, 1.0)
        if not c3_ok:
            score = min(score, 0.55)

        passed = score >= 0.8
        return passed, score

    def get_task_summary(self) -> str:
        return (
            "Semantic paradox detection in legal/PR text. Model must find "
            "genuine contradictions among 10 statements, not hallucinate "
            "fake conflicts. Tests data auditing in a non-technical domain."
        )
