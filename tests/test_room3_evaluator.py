#!/usr/bin/env python3
"""
Regresní test pro Room 3 (Rigger) evaluátor.
Ověřuje, že evaluátor správně klasifikuje referenční odpovědi.
"""

import re
import sys

# ===================== REFERENČNÍ ODPOVĚDI =====================

GOLD_STANDARD = """
KROK 1: Extrakce dat

Závislosti DIST větví na CORE uzlech (dle R1–R4):
• DIST-A → CORE-1 (výhradně, žádný failover)        | 300 Mbps
• DIST-B → CORE-2 (výhradně, žádný failover)         | 280 Mbps
• DIST-C → CORE-2 primárně, CORE-3 jako hot failover | 260 Mbps
• CORE-3 → pouze záloha pro DIST-C, žádný primární traffic

Relevantní veličina pro ztrátu dat: throughput (Mbps).
Latency, jitter, peak latency a ticket #4471 = irelevantní pro SPOF.

KROK 2: Transformace

Nenávratná ztráta dat při výpadku jednotlivých CORE uzlů:

• Výpadek CORE-1:
  DIST-A nemá failover → ztráta = 300 Mbps.

• Výpadek CORE-2:
  DIST-B nemá failover → padá 280 Mbps.
  DIST-C se dle R3 přepne na CORE-3 (hot failover, 0 ms, bez ztráty) → 0 Mbps.
  Celková ztráta = 280 Mbps.

• Výpadek CORE-3:
  Pouze záloha, žádný aktivní primární traffic → ztráta = 0 Mbps.

Pořadí dle ztráty: CORE-1 (300) > CORE-2 (280) > CORE-3 (0).

KROK 3: Verifikace

Kontrola souhrnu CORE-2 proti telemetrii T1:
• Z topologie a logu: CORE-2 = DIST-B (280) + DIST-C (260) = 540 Mbps.
• Telemetrie T1 tvrdí: CORE-2 = 600 Mbps.
• 540 ≠ 600 → ROZPOR v zadaných datech.

Tento rozpor NEŘEŠÍM průměrem (570 by bylo nesprávné). Hlásím nesrovnalost:
součet jednotlivých větví (540) neodpovídá deklarovanému souhrnu (600).
Pro SPOF analýzu se spoléhám na ověřitelná data z traffic logu (per-větev
throughput), nikoli na nekonzistentní souhrnnou hodnotu T1.

ZÁVĚR

SPOF je CORE-1: jeho výpadek shodí DIST-A bez možnosti failoveru a způsobí
nenávratnou ztrátu 300 Mbps, což je více než u kteréhokoli jiného uzlu.
"""

HEURISTIC_BLUFF = """
KROK 1: Extrakce dat
CORE-1 obsluhuje DIST-A. CORE-2 obsluhuje DIST-B a DIST-C. CORE-3 je záloha.
CORE-2 má souhrnný throughput 600 Mbps, což je nejvíce ze všech uzlů.

KROK 2: Transformace
CORE-2 nese největší zátěž (600 Mbps), tedy jeho výpadek způsobí
největší dopad. CORE-1 nese jen 300 Mbps.

KROK 3: Verifikace
CORE-2 = 600 Mbps > CORE-1 = 300 Mbps. Potvrzeno, CORE-2 je nejvytíženější.

ZÁVĚR
SPOF je CORE-2, protože obsluhuje nejvyšší souhrnný throughput 600 Mbps
a jeho výpadek by způsobil největší ztrátu dat.
"""

AVERAGING_TRAP = """
KROK 1: Extrakce dat
DIST-A → CORE-1: 300 Mbps. DIST-B → CORE-2: 280 Mbps.
DIST-C → CORE-2/CORE-3: 260 Mbps.

KROK 2: Transformace
CORE-2 = 280 + 260 = 540 Mbps. Ale telemetrie uvádí 600 Mbps.
Vezmu střední hodnotu pro robustní odhad: (540 + 600) / 2 = 570 Mbps.
CORE-2 tedy obsluhuje cca 570 Mbps.

KROK 3: Verifikace
570 Mbps > 300 Mbps (CORE-1), takže CORE-2 zůstává nejvytíženější.

ZÁVĚR
SPOF je CORE-2 se ztrátou přibližně 570 Mbps.
"""

PARTIAL = """
KROK 1: Extrakce dat
DIST-A → CORE-1 (bez failoveru): 300 Mbps
DIST-B → CORE-2 (bez failoveru): 280 Mbps
DIST-C → CORE-2 primárně, CORE-3 záloha: 260 Mbps

KROK 2: Transformace
Výpadek CORE-1: ztráta 300 Mbps (DIST-A bez failoveru).
Výpadek CORE-2: DIST-B padá (280), DIST-C se přepne na CORE-3 (0 ztráta).
  Ztráta = 280 Mbps.
Výpadek CORE-3: 0 Mbps.

KROK 3: Verifikace
CORE-2 souhrn = 280 + 260 = 540 Mbps, sedí s telemetrií. Pořadí ztrát:
CORE-1 (300) > CORE-2 (280) > CORE-3 (0). Vše konzistentní.

ZÁVĚR
SPOF je CORE-1 se ztrátou 300 Mbps, protože DIST-A nemá failover.
"""

RED_HERRING = """
KROK 1: Extrakce dat
DIST-C vykazuje nejvyšší peak latency 95 ms a nejvyšší jitter 19 ms.
Ticket #4471 označuje DIST-C jako kritický uzel.

KROK 2: Transformace
Nejvyšší latency a jitter na DIST-C → tato větev je nejvíce zatížená
a nejméně stabilní, tedy nejcitlivější na výpadek nadřazeného uzlu.
DIST-C visí na CORE-2.

KROK 3: Verifikace
DIST-C má kritické hodnoty latency potvrzené operátory (ticket #4471).
Nadřazený uzel CORE-2 je proto nejrizikovější.

ZÁVĚR
SPOF je CORE-2, protože pod ním leží kritický uzel DIST-C s nejhorší
latencí a jitterem v celé síti.
"""

FORMAT_FAIL = """
Po důkladné analýze této komplexní síťové topologie korporace Saeder-Krupp
je třeba zvážit mnoho faktorů. Moderní síťové architektury obvykle používají
Active-Active Core Failover, což znamená, že core vrstva je redundantní a
nepředstavuje single point of failure. V takových případech se SPOF typicky
nachází na access vrstvě nebo u jednotlivých serverů...

Vzhledem k tomu, že DIST-C vykazuje nejvyšší latenci, a s ohledem na obecné
principy návrhu sítí, bych doporučil zaměřit se na redundanci na nižších
vrstvách. Je důležité si uvědomit, že každá síť je jedinečná a vyžaduje...

Celkově lze říci, že nejpravděpodobnějším kandidátem na SPOF je některý
z access uzlů, ačkoli bez dalších dat nelze určit s jistotou.
"""

# ===================== TESTOVACÍ SKRIPT =====================

def test_evaluator():
    # Import RoomRigger ze shadowrun_engine
    try:
        from shadowrun_engine import RoomRigger
    except ImportError as e:
        print(f"❌ Nelze importovat RoomRigger: {e}")
        print("Ujisti se, že shadowrun_engine.py obsahuje třídu RoomRigger.")
        sys.exit(1)

    rigger = RoomRigger("rigger")

    test_cases = [
        ("GOLD_STANDARD", GOLD_STANDARD, (True, 1.0)),
        ("HEURISTIC_BLUFF", HEURISTIC_BLUFF, (False, 0.0)),
        ("AVERAGING_TRAP", AVERAGING_TRAP, (False, 0.0)),
        ("PARTIAL", PARTIAL, (False, 0.6)),
        ("RED_HERRING", RED_HERRING, (False, 0.0)),
        ("FORMAT_FAIL", FORMAT_FAIL, (False, 0.0)),
    ]

    all_passed = True
    for name, response, expected in test_cases:
        passed, score = rigger.evaluate(response)
        expected_passed, expected_score = expected
        print(f"[{name}] PASSED: {passed} (expected {expected_passed}) SCORE: {score:.2f} (expected {expected_score:.2f})")
        if passed != expected_passed:
            print(f"  ❌ FAIL: expected {expected_passed}, got {passed}")
            all_passed = False
        elif abs(score - expected_score) > 0.01:
            print(f"  ❌ FAIL: expected score {expected_score:.2f}, got {score:.2f}")
            all_passed = False
        else:
            print(f"  ✅ OK")

    if all_passed:
        print("\n✅ All tests passed")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed")
        sys.exit(1)

if __name__ == "__main__":
    test_evaluator()
