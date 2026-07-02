#!/usr/bin/env python3
"""
MGD Team — Semantic Judge Module.
2. stupeň evaluace: když regex netrefí, Phi-4 posoudí věcnou správnost
odpovědi proti GOLD_STANDARD a vrátí známku 2-5 (1 = nejlepší, vyhrazeno pro regex).
"""
import json
import re
import httpx

OLLAMA_URL = "http://localhost:11434/api/generate"
JUDGE_MODEL = "phi4:latest"
FALLBACK_GRADE = 5  # Phi-4 nedostupná / neparsovatelná → nejhorší známka

JUDGE_PROMPT_HEADER = """You are a strict but fair technical grader.
Compare the MODEL RESPONSE against the REFERENCE ANSWER for the given QUESTION.
Grade ONLY factual correctness: does the response contain the key concepts
of the reference, even if worded differently? IGNORE form, grammar, and style.
Use Czech school grading where 1 is best and 5 is worst:
  2 = correct, minor imprecision or a missing detail
  3 = partially correct, captures about half of the key concepts
  4 = mostly wrong, only a hint of correctness
  5 = wrong, off-topic, or empty
(Grade 1 is reserved for an exact keyword match and is never assigned by you.)
Output JSON ONLY, nothing else: {"grade": <2-5>, "reason": "short justification"}
"""

def _extract_json(text: str) -> dict | None:
    """Robustní vytažení prvního JSON objektu bez ohledu na balast a markdown obaly."""
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

def _build_prompt(question: str, model_response: str, reference_answer: str) -> str:
    return (
        JUDGE_PROMPT_HEADER
        + f"\nQUESTION:\n{question}\n"
        + f"\nREFERENCE ANSWER (gold standard):\n{reference_answer}\n"
        + f"\nMODEL RESPONSE:\n{model_response}\n"
    )

async def judge_semantic(question: str, model_response: str, reference_answer: str) -> dict:
    """
    Volá Phi-4 přes lokální Ollamu a parsuje sémantické hodnocení 2. stupně.
    """
    if not model_response or not model_response.strip():
        return {"grade": 5, "reason": "Prázdná odpověď modelu."}
    
    prompt = _build_prompt(question, model_response, reference_answer)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(OLLAMA_URL, json={
                "model": JUDGE_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0}  # Absolutní determinismus
            })
            if response.status_code == 200:
                raw = response.json().get("response", "").strip()
                parsed = _extract_json(raw)
                if parsed is not None:
                    grade = parsed.get("grade")
                    reason = str(parsed.get("reason", "")).strip()
                    try:
                        grade = int(grade)
                    except (TypeError, ValueError):
                        grade = None
                    
                    if grade in (2, 3, 4, 5):
                        return {"grade": grade, "reason": reason or "Bez odůvodnění."}
                    if grade == 1:
                        print("[JUDGE] Phi-4 vrátila chráněnou známku 1 → mapuji na 2")
                        return {"grade": 2, "reason": reason or "Model ohodnocen jako plně sémanticky správný."}
                    print(f"[JUDGE] Grade mimo povolený rozsah ({grade}) → fallback na 5")
                else:
                    print("[JUDGE] Nelze parsovat JSON z výstupu Phi-4.")
            else:
                print(f"[JUDGE] API chybový stav: {response.status_code}")
    except Exception as e:
        print(f"[JUDGE] Výjimka při komunikaci s Phi-4: {e}")
    
    return {"grade": FALLBACK_GRADE, "reason": "Interní chyba arbitráže (soudce spadl nebo timeoutoval)."}

async def grade_response(question: str, model_response: str, reference_answer: str, regex_pattern: str = "") -> dict:
    """
    Orchestrátor dvoustupňové evaluace.
    Stage 1: Rychlá regex trefa → známka 1.
    Stage 2: Fallback na Phi-4 sémantiku → známka 2-5.
    Pokud je regex_pattern prázdný, Stage 1 se bezpečně přeskočí.
    """
    if regex_pattern and re.search(regex_pattern, model_response or "", re.IGNORECASE):
        return {"grade": 1, "reason": "První stupeň: Výstup odpovídá exaktnímu regulárnímu vzoru.", "stage": "regex"}
    
    result = await judge_semantic(question, model_response, reference_answer)
    result["stage"] = "semantic"
    return result

if __name__ == "__main__":
    import argparse
    import asyncio
    parser = argparse.ArgumentParser(description="MGD Semantic Judge — CLI ověření")
    parser.add_argument("--question", required=True)
    parser.add_argument("--response", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--regex", default="")
    args = parser.parse_args()
    
    async def run():
        out = await grade_response(args.question, args.response, args.reference, args.regex)
        print("\n=== FINÁLNÍ ARBITRÁŽNÍ PROTOKOL ===")
        print(json.dumps(out, indent=2, ensure_ascii=False))
    asyncio.run(run())
