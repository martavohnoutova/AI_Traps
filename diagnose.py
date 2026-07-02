#!/usr/bin/env python3
"""
MGD Team — Diagnostický modul s Mistral Large.
Nezávislý na enginu. Importuj nebo spusť jako CLI.

Použití:
    python3 diagnose.py --run-id 15
    python3 diagnose.py --model mistral:7b --room room_3
    python3 diagnose.py --all
    python3 diagnose.py --all --output report.md
"""

import sqlite3
import httpx
import asyncio
import argparse
import json
import sys
import os
from datetime import datetime

# === KONFIGURACE ==============================================

DB_PATH = "/mnt/private/n8n/shadowrun.db"
OLLAMA_URL = "http://localhost:11434/api/generate"
#JUDGE_MODEL = "mistral-large:latest"
JUDGE_MODEL = "phi4:latest"  # nebo "mistral-large:latest"
JUDGE_TIMEOUT = 180  # 4 minuty — Mistral Large je 73 GB

# === PROMPTY ===================================================

PROMPT_SINGLE = """Jsi expertní posuzovatel AI modelů v benchmarku "Pasti na AI".
Dostaneš odpověď testovaného modelu a skóre z evaluátoru.
Napiš STRUČNOU diagnostiku.

=== KONTEXT ===
Místnost: {room_name} ({room_id})
Testovaný model: {model_name}
Skóre evaluátoru: {score:.2f} (PASS pokud >= 0.8)

=== ODPOVĚĎ MODELU ===
{raw_response}

=== VÝSTUP (JSON) ===
Odpověz POUZE validním JSON. Žádný komentář mimo JSON.
{{
    "strengths": "1-2 věty: co model udělal správně",
    "weaknesses": "1-2 věty: kde selhal a proč",
    "typology": "jednoslovná typologie: Auditor / Počtář / Chaos / Kolaps / Formát",
    "verdict": "jedno slovo: PASS nebo FAIL"
}}
"""

PROMPT_ALL = """Jsi expertní posuzovatel AI benchmarku "Pasti na AI".
Dostaneš KOMPLETNÍ výsledky testování všech modelů ve všech místnostech.
Napiš souhrnnou analytickou zprávu.

=== STRUKTURA ===
1. EXECUTIVE SUMMARY (3-4 věty)
2. POROVNÁNÍ MODELŮ (tabulka nebo seznam)
3. ANALÝZA PODLE MÍSTNOSTÍ (která místnost byla nejtěžší, kde selhávaly i silné modely)
4. KLÍČOVÉ NÁLEZY (co benchmark odhalil o schopnostech modelů)
5. DOPORUČENÍ (co testovat dál, jaké úpravy benchmarku)

=== DATA ===
{data_text}

=== VÝSTUP ===
Piš v češtině nebo angličtině (podle dat). Strukturovaný text, žádný JSON.
"""

ROOM_NAMES = {
    "room_1": "Samuraj — Dual Objective Extraction",
    "room_2": "Decker — Race Condition Detection",
    "room_3": "Rigger — SPOF Analysis with Data Audit",
    "room_4": "Face — Semantic Paradox Detection",
}


# === JÁDRO =====================================================

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


async def call_mistral(prompt: str) -> str:
    """Zavolá Mistral Large a vrátí odpověď."""
    async with httpx.AsyncClient(timeout=JUDGE_TIMEOUT) as client:
        response = await client.post(OLLAMA_URL, json={
            "model": JUDGE_MODEL,
            "prompt": prompt,
            "stream": False
        })
        if response.status_code != 200:
            return f"CHYBA: HTTP {response.status_code}"
        return response.json().get("response", "").strip()


async def diagnose_single(
    raw_response: str,
    score: float,
    room_id: str,
    model_name: str
) -> dict:
    """Diagnostika jedné odpovědi. Vrací dict."""
    room_name = ROOM_NAMES.get(room_id, room_id)
    prompt = PROMPT_SINGLE.format(
        room_name=room_name,
        room_id=room_id,
        model_name=model_name,
        score=score,
        raw_response=raw_response[:2000]  # oříznutí pro úsporu tokenů
    )
    print(f"  🧠 Microsoft Phi posuzuje {model_name} v {room_id}...", flush=True)
    result = await call_mistral(prompt)
    try:
        # Vyčistit Markdown fences
        if "```" in result:
            result = result.split("```")[1]
            if result.startswith("json"):
                result = result[4:]
        return json.loads(result.strip())
    except json.JSONDecodeError:
        return {
            "strengths": "CHYBA PARSU",
            "weaknesses": "CHYBA PARSU",
            "typology": "Neznámý",
            "verdict": "ERROR",
            "raw_judge_response": result
        }


async def diagnose_all(output_path: str | None = None) -> str:
    """Souhrnná zpráva ze všech runů. Vrací text."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.room_id, a.agent_role, a.model_name, a.status, a.score_change,
               a.raw_response, a.timestamp
        FROM action_log a
        ORDER BY a.timestamp
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "❌ Žádná data v action_log."

    # Sestav textový přehled
    lines = []
    current_model = None
    for row in rows:
        model = row["model_name"]
        if model != current_model:
            current_model = model
            lines.append(f"\n=== {model} ===")
        room_name = ROOM_NAMES.get(row["room_id"], row["room_id"])
        lines.append(
            f"  {room_name}: status={row['status']}, "
            f"score_change={row['score_change']}"
        )

    data_text = "\n".join(lines)

    print("  🧠 Microsoft Phi generuje souhrnnou zprávu...", flush=True)
    prompt = PROMPT_ALL.format(data_text=data_text[:3000])
    report = await call_mistral(prompt)

    if output_path:
        with open(output_path, "w") as f:
            f.write(f"# MGD Shadowrun Benchmark — Souhrnná zpráva\n")
            f.write(f"Vygenerováno: {datetime.now().isoformat()}\n\n")
            f.write(report)
        print(f"  ✅ Report uložen do {output_path}", flush=True)

    return report


# === CLI ========================================================

async def main():
    parser = argparse.ArgumentParser(description="MGD Diagnostika s Microsoft Phi")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id", type=int, help="ID záznamu z action_log")
    group.add_argument("--model", type=str, help="Model + --room")
    group.add_argument("--all", action="store_true", help="Souhrnná zpráva")
    parser.add_argument("--room", type=str, help="Místnost (s --model)")
    parser.add_argument("--output", type=str, help="Uložit report do souboru")

    args = parser.parse_args()

    if args.all:
        report = await diagnose_all(args.output)
        print(report)

    elif args.run_id:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM action_log WHERE id = ?", (args.run_id,))
        row = cur.fetchone()
        conn.close()

        if not row:
            print(f"❌ Záznam s ID {args.run_id} nenalezen.")
            sys.exit(1)

        # Zjisti skóre — pro Room 1-4 použijeme status
        score = 1.0 if row["status"] == "success" else 0.0
        diag = await diagnose_single(
            raw_response=row["raw_response"],
            score=score,
            room_id=row["room_id"],
            model_name=row["model_name"]
        )
        print(json.dumps(diag, ensure_ascii=False, indent=2))

    elif args.model:
        if not args.room:
            print("❌ S --model musíš zadat i --room.")
            sys.exit(1)

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM action_log WHERE model_name=? AND room_id=? ORDER BY id DESC LIMIT 1",
            (args.model, args.room)
        )
        row = cur.fetchone()
        conn.close()

        if not row:
            print(f"❌ Záznam pro {args.model} v {args.room} nenalezen.")
            sys.exit(1)

        score = 1.0 if row["status"] == "success" else 0.0
        diag = await diagnose_single(
            raw_response=row["raw_response"],
            score=score,
            room_id=row["room_id"],
            model_name=row["model_name"]
        )
        print(json.dumps(diag, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
