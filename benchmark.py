#!/usr/bin/env python3
"""
Benchmark – otestuje všechny kombinace modelů na Shadowrun enginu.
"""

import subprocess
import json
import sqlite3
import time
import datetime
import os
import sys
import random

# Maximální počet spuštěných kombinací v jednom běhu (pro zamezení extrémně dlouhému běhu při velkém množství modelů)
# Nastavte na None pro spuštění všech možných kombinací
MAX_RUNS = None

def get_models_from_ollama():
    """
    Spustí 'ollama list' a parsuje výstup (jméno modelu).
    Vrátí seznam dostupných modelů.
    """
    try:
        res = subprocess.run(['ollama', 'list'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        models = []
        for line in res.stdout.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('NAME'):
                continue
            parts = line.split()
            if parts:
                models.append(parts[0])
        return models
    except Exception as e:
        print(f"Chyba při volání 'ollama list': {e}", file=sys.stderr)
        return []

def run_game_for_combination(samurai_model, decker_model, rigger_model, face_model, intro_duration=None, vote_duration=None, result_duration=None, no_video=False):
    """
    Sestaví CLI argumenty: --samurai, --decker, --rigger, --face.
    Spustí shadowrun_engine.py jako subprocess.
    Počká na dokončení (timeout 120s).
    Přečte audit_log.json a extrahuje výsledky (skóre pro každou místnost).
    """
    # Sestavit příkaz pro spuštění subprocessu
    cmd = [sys.executable, 'shadowrun_engine.py']
    if samurai_model:
        cmd += ['--samurai', samurai_model]
    if decker_model:
        cmd += ['--decker', decker_model]
    if rigger_model:
        cmd += ['--rigger', rigger_model]
    if face_model:
        cmd += ['--face', face_model]
    cmd.append('--benchmark')
    if intro_duration is not None: cmd += ['--intro-duration', str(intro_duration)]
    if vote_duration is not None: cmd += ['--vote-duration', str(vote_duration)]
    if result_duration is not None: cmd += ['--result-duration', str(result_duration)]
    if no_video: cmd.append('--no-video')

    print(f"\nSpouštím shadowrun_engine.py pro modely:")
    print(f"  Samurai: {samurai_model}")
    print(f"  Decker:  {decker_model}")
    print(f"  Rigger:  {rigger_model}")
    print(f"  Face:    {face_model}")

    # Spustit uvicorn server na pozadí
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    print(f"[BENCH] Čekám na dokončení hry...")
    try:
        proc.wait(timeout=400)
    except subprocess.TimeoutExpired:
        proc.kill()

    # Vypis stdout a stderr po ukončení
    try:
        stdout, stderr = proc.communicate()
        print("[BENCH] Subprocess stdout:")
        print(stdout)
        print("[BENCH] Subprocess stderr:")
        print(stderr)
    except Exception as e:
        print(f"[BENCH] Chyba při čtení výstupů subprocessu: {e}", file=sys.stderr)

    # Krátký sleep pro uvolnění portu pro další běhy
    time.sleep(1.5)

    # Přečíst výsledky z DB nebo nastavit penalizaci
    room_scores = {
        "room_1": -10,
        "room_2": -10,
        "room_3": -10,
        "room_4": -10
    }

    if proc.returncode == 0:
        try:
            conn = sqlite3.connect("/mnt/private/n8n/shadowrun.db")
            cur = conn.cursor()
            cur.execute("SELECT room_id, score_change FROM action_log")
            rows = cur.fetchall()
            conn.close()
            for room_id, score_change in rows:
                if room_id in room_scores:
                    room_scores[room_id] = score_change
        except Exception as e:
            print(f"[BENCH] Chyba při čtení skóre z DB: {e}", file=sys.stderr)

    room_scores["total"] = sum(room_scores[r] for r in ["room_1", "room_2", "room_3", "room_4"])
    return room_scores

def save_results(combination, results):
    """
    Uloží do tabulky benchmark_results v shadowrun.db:
      id, timestamp, samurai_model, decker_model, rigger_model, face_model,
      room_1_score, room_2_score, room_3_score, room_4_score, total_score
    Pokud tabulka neexistuje, vytvoř ji.
    """
    samurai_model, decker_model, rigger_model, face_model = combination
    samurai_model = samurai_model if samurai_model is not None else "None"
    decker_model = decker_model if decker_model is not None else "None"
    rigger_model = rigger_model if rigger_model is not None else "None"
    face_model = face_model if face_model is not None else "None"
    room_1_score = results.get("room_1", 0)
    room_2_score = results.get("room_2", 0)
    room_3_score = results.get("room_3", 0)
    room_4_score = results.get("room_4", 0)
    total_score = results.get("total", 0)
    
    timestamp = datetime.datetime.now().isoformat()
    
    conn = sqlite3.connect("/mnt/private/n8n/shadowrun.db")
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS benchmark_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            samurai_model TEXT NOT NULL,
            decker_model TEXT NOT NULL,
            rigger_model TEXT NOT NULL,
            face_model TEXT NOT NULL,
            room_1_score INTEGER NOT NULL,
            room_2_score INTEGER NOT NULL,
            room_3_score INTEGER NOT NULL,
            room_4_score INTEGER NOT NULL,
            total_score INTEGER NOT NULL
        )
    """)
    
    cur.execute("""
        INSERT INTO benchmark_results (
            timestamp, samurai_model, decker_model, rigger_model, face_model,
            room_1_score, room_2_score, room_3_score, room_4_score, total_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        timestamp, samurai_model, decker_model, rigger_model, face_model,
        room_1_score, room_2_score, room_3_score, room_4_score, total_score
    ))
    
    conn.commit()
    conn.close()

def reset_database():
    try:
        conn = sqlite3.connect("/mnt/private/n8n/shadowrun.db")
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS action_log (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT, agent_role TEXT, model_name TEXT, raw_response TEXT, status TEXT, score_change INTEGER DEFAULT 0, diagnostics TEXT, timestamp REAL, grade INTEGER, stage TEXT)")
        cur.execute("DELETE FROM action_log")
        cur.execute("DELETE FROM votes")
        cur.execute("UPDATE game_state SET phase = 'intro', current_room_id = 'room_intro', timer_start = NULL, chosen_option = NULL, result_text = '', score = 0 WHERE id = 1")
        conn.commit()
        conn.close()
        print("[BENCH] Databáze byla resetována.")
    except Exception as e:
        print(f"[BENCH] Chyba při resetování databáze: {e}", file=sys.stderr)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--intro-duration', type=float, default=None)
    parser.add_argument('--vote-duration', type=float, default=None)
    parser.add_argument('--result-duration', type=float, default=None)
    parser.add_argument('--no-video', action='store_true')
    parser.add_argument('--max-runs', type=int, default=None)
    args, _ = parser.parse_known_args()
    global MAX_RUNS
    if args.max_runs is not None: MAX_RUNS = args.max_runs
    intro_duration = args.intro_duration
    vote_duration = args.vote_duration
    result_duration = args.result_duration
    no_video = args.no_video
    """
    Získá modely z Ollamy.
    Pro každou kombinaci modelů spustí run_game_for_combination.
    Uloží výsledky a vypíše přehlednou tabulku.
    """
    models = get_models_from_ollama()
    if not models:
        print("Nebyly nalezeny žádné modely v Ollamě. Benchmark ukončen.", file=sys.stderr)
        return

    print(f"Nalezené modely v Ollamě: {models}")

    # Generování her s využitím fronty úkolů
    from collections import deque
    tasks = deque((model, role) for model in models for role in ["samurai", "decker", "rigger", "face"])

    combinations = []
    while tasks:
        game = {}
        for role in ["samurai", "decker", "rigger", "face"]:
            # Najdi první úkol pro tuto roli
            for task in tasks:
                if task[1] == role:
                    game[role] = task[0]
                    tasks.remove(task)
                    break
            else:
                game[role] = None
        combinations.append(
            (game.get("samurai"), game.get("decker"), game.get("rigger"), game.get("face"))
        )

    random.seed(42)  # pro replikovatelnost
    random.shuffle(combinations)

    total_combinations = len(combinations)
    print(f"Celkový počet možných kombinací modelů: {total_combinations}")

    # Aplikace limitu na počet běhů, aby benchmark neběžel příliš dlouho
    if MAX_RUNS is not None and total_combinations > MAX_RUNS:
        print(f"\n[INFO] Počet kombinací ({total_combinations}) převyšuje nastavený limit MAX_RUNS={MAX_RUNS}.")
        print(f"Spustíme pouze prvních {MAX_RUNS} kombinací.")
        print(f"Pro změnu chování upravte hodnotu konstanty MAX_RUNS v souboru benchmark.py.")
        combinations = combinations[:MAX_RUNS]

    session_results = []

    for idx, combo in enumerate(combinations):
        print(f"\n==========================================")
        print(f"Spouštím kombinaci {idx+1}/{len(combinations)}")
        print(f"==========================================")
        
        reset_database()
        samurai, decker, rigger, face = combo
        results = run_game_for_combination(samurai, decker, rigger, face, intro_duration=intro_duration, vote_duration=vote_duration, result_duration=result_duration, no_video=no_video)
        
        save_results(combo, results)
        session_results.append({
            "combination": combo,
            "results": results
        })

    # Vypis přehledné tabulky s výsledky
    print("\n" + "="*115)
    print("VÝSLEDKY BENCHMARKU TÉTO RELACE")
    print("="*115)
    print(f"{'Samuraj':<18} | {'Decker':<18} | {'Rigger':<18} | {'Face':<18} | {'R1':>4} | {'R2':>4} | {'R3':>4} | {'R4':>4} | {'Celkem':>6}")
    print("-"*115)
    for res in session_results:
        samurai, decker, rigger, face = res["combination"]
        r = res["results"]
        print(f"{samurai:<18} | {decker:<18} | {rigger:<18} | {face:<18} | {r['room_1']:>4} | {r['room_2']:>4} | {r['room_3']:>4} | {r['room_4']:>4} | {r['total']:>6}")
    print("="*115)

if __name__ == "__main__":
    main()
