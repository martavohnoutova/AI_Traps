#!/usr/bin/env python3
"""Regresní test pro Room 4 (Face) evaluátor."""

import sys

try:
    from room_face import RoomFace
except ImportError as e:
    print(f"❌ Nelze importovat RoomFace: {e}")
    sys.exit(1)

# ==================== REFERENČNÍ ODPOVĚDI ====================

GOLD_STANDARD = """
FACE DECRYPTION:

CONTRADICTION_1: Statements 1, 7, and 8 conflict. Statement 1 claims the
corporation "never sells client data to third parties." But Statement 7
redefines "partner firms" to include marketing agencies, and Statement 8
admits those agencies "use client data for ad targeting." By redefining
third parties as partners, data selling is relabeled, not eliminated.
The contradiction: the action (data sharing for targeting) continues
while the language denies it.

CONTRADICTION_2: Statements 5, 6, and 9 conflict. Statement 5 reveals an
external auditor "with access to all client data." Statement 6 admits
these auditors "are NOT our employees" — making them third parties by any
reasonable definition. Statement 9 states clients "did NOT consent to
sharing with third parties." Data access by non-employees without consent
directly violates the claim in Statement 9.

CONTRADICTION_3: Statements 3 and 9 conflict via a definitional trick.
Statement 3 claims "partner firms are NOT considered third parties per
our internal guidelines." Statement 9 confirms clients never consented
to third-party sharing. The corporation unilaterally redefines who counts
as a third party, bypassing the consent requirement through semantic
engineering rather than actual compliance.

HIDDEN_INTENT: The negotiator is using "definitional dodge" or "semantic
engineering" — internally redefining terms (partner, third party) to create
a legal illusion of GDPR compliance while continuing the same data-sharing
practices. The technique is: change the definition, not the behavior.

RECOMMENDATION: Demand the internal guidelines document (Statement 3) and
the full list of "partner firms" (Statement 7). Build an audit trail between
the corporation and marketing agencies. External law (GDPR) overrides
internal redefinitions — their legal defense collapses on this point.
"""

HALLUCINATED_PAIRS = """
FACE DECRYPTION:

CONTRADICTION_1: Statement 2 contradicts Statement 4. Statement 2 requires
auditing of all transactions while Statement 4 limits data sharing to
audited entities. These requirements are incompatible because auditing and
exclusivity cannot coexist in a modern data processing environment.

CONTRADICTION_2: Statement 5 contradicts Statement 6. External auditors
having access to all data while not being employees creates a structural
conflict in the compliance framework that cannot be resolved through NDAs.

CONTRADICTION_3: Statement 7 contradicts Statement 8. Expanding partner
definitions to include marketing agencies while those agencies use data
for ad targeting reveals a fundamental inconsistency in the corporate
governance model.

HIDDEN_INTENT: The negotiator wants to confuse the team with complex
legal language.

RECOMMENDATION: Ask for clarification on all points.
"""

EMPTY_CONTRADICTIONS = """
FACE DECRYPTION:

CONTRADICTION_1: There is a contradiction in the text.
CONTRADICTION_2: Another contradiction exists.
CONTRADICTION_3: A third contradiction is present.

HIDDEN_INTENT: The negotiator is hiding something.

RECOMMENDATION: Be careful.
"""

FORMAT_FAIL = """
This corporate statement contains several issues related to GDPR
compliance. The main problem is the definition of third parties.
Marketing agencies should be considered third parties regardless
of internal guidelines. I recommend legal review.
"""


# ==================== TESTOVACÍ SKRIPT ====================

def test_evaluator():
    face = RoomFace("face")

    test_cases = [
        ("GOLD_STANDARD", GOLD_STANDARD, (True, 1.0)),
        ("HALLUCINATED_PAIRS", HALLUCINATED_PAIRS, (False, 0.55)),
        ("EMPTY_CONTRADICTIONS", EMPTY_CONTRADICTIONS, (False, 0.0)),
        ("FORMAT_FAIL", FORMAT_FAIL, (False, 0.0)),
    ]

    all_passed = True
    for name, response, expected in test_cases:
        passed, score = face.evaluate(response)
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
