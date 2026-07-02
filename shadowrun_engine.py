#!/usr/bin/env python3
"""
MGD Team – Shadowrun "Pasti na AI" – herní engine
FastAPI + SQLite, generické schéma.
Verze 3.2: Oprava by Opičák & Marta (narovnání by-design časování by_advance).
"""

import asyncio
import time
import os
import sqlite3
import httpx
import subprocess
import sys
import json
import abc
import re
import argparse
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Dict

from room_rigger import RoomRigger
from room_samuraj import RoomSamuraj
from room_decker import RoomDecker
from room_face import RoomFace

# Import sémantického orchestrátoru od Opičáka
from semantic_judge import grade_response
from voting_backend import init_voting_db, generate_session_id, register_voting_endpoints, model_score_to_grade

AUDIT_LOG_PATH = '/mnt/private/n8n/audit_log.json'

# ===================== CLI ARGUMENTY =====================
parser = argparse.ArgumentParser(description="MGD Shadowrun Engine")
parser.add_argument("--samurai", type=str, help="Model pro Samuraje")
parser.add_argument("--decker", type=str, help="Model pro Deckera")
parser.add_argument("--rigger", type=str, help="Model pro Riggera")
parser.add_argument("--face", type=str, help="Model pro Face")
parser.add_argument("--benchmark", action="store_true", help="Spustit v benchmark módu se zrychleným časováním")

parser.add_argument("--intro-duration", type=float, default=None, help="Trvání intro fáze v sekundách")
parser.add_argument("--vote-duration", type=float, default=None, help="Trvání hlasování v sekundách")
parser.add_argument("--result-duration", type=float, default=None, help="Trvání zobrazení výsledků v sekundách")
parser.add_argument("--no-video", action="store_true", help="Vypne přehrávání herních videí na frontendu")
parser.add_argument("--room", type=str, help="Spustit pouze tuto místnost (např. room_3)")

args, _ = parser.parse_known_args()

# ===================== DYNAMICKÉ KONSTANTY =====================
if args.benchmark:
    base_intro = 0.1
    base_vote = 0.5
    base_result = 0.1
else:
    base_intro = 12.0
    base_vote = 12.0
    base_result = 10.0  # Opičákův čistý základ

INTRO_DURATION = args.intro_duration if args.intro_duration is not None else base_intro
VOTE_DURATION = args.vote_duration if args.vote_duration is not None else base_vote
RESULT_DURATION = args.result_duration if args.result_duration is not None else base_result
PLAY_VIDEO = not args.no_video
TARGET_ROOM = args.room

MAX_RESPONSE_TIME = 360.0    # timeout pro Ollamu
OLLAMA_URL = "http://localhost:11434/api/generate"
DB_PATH = "/mnt/private/n8n/shadowrun.db"
SHADOW_MODE = False

# ===================== INICIALIZACE MÍSTNOSTÍ =====================
ROOM_CLASSES = {
    "room_1": RoomSamuraj("samuraj"),
    "room_2": RoomDecker("decker"),
    "room_3": RoomRigger("rigger"),
    "room_4": RoomFace("face")
}

# ===================== DATABÁZE =====================
def init_db():
    os.makedirs("/mnt/private/n8n/assets", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    for tbl in ["votes", "role_hp", "options", "game_state", "rooms", "roles"]:
        c.execute(f"DROP TABLE IF EXISTS {tbl}")

    c.execute("""
        CREATE TABLE roles (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, icon_asset TEXT, model_name TEXT
        )
    """)
    c.execute("""
        CREATE TABLE rooms (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
            background_asset TEXT, success_asset TEXT, fail_asset TEXT, next_room_id TEXT
        )
    """)
    c.execute("""
        CREATE TABLE options (
            id TEXT PRIMARY KEY, room_id TEXT NOT NULL, letter TEXT NOT NULL, text TEXT NOT NULL,
            required_role_id TEXT, is_correct INTEGER NOT NULL, score_change INTEGER NOT NULL,
            prompt_template TEXT, FOREIGN KEY(room_id) REFERENCES rooms(id), FOREIGN KEY(required_role_id) REFERENCES roles(id)
        )
    """)
    c.execute("""
        CREATE TABLE game_state (
            id INTEGER PRIMARY KEY CHECK (id = 1), phase TEXT NOT NULL DEFAULT 'intro',
            current_room_id TEXT, timer_start REAL, chosen_option TEXT, result_text TEXT,
            score INTEGER DEFAULT 0, game_session_id TEXT, current_model_name TEXT,
            voting_open INTEGER DEFAULT 0, calculated_grade INTEGER DEFAULT NULL
        )
    """)
    c.execute("""
        CREATE TABLE role_hp (
            role_id TEXT PRIMARY KEY, current_hp INTEGER NOT NULL DEFAULT 100, FOREIGN KEY(role_id) REFERENCES roles(id)
        )
    """)
    c.execute("""
        CREATE TABLE votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, option_letter TEXT NOT NULL, voter_id TEXT, timestamp REAL, FOREIGN KEY(room_id) REFERENCES rooms(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, agent_role TEXT NOT NULL,
            model_name TEXT, raw_response TEXT, status TEXT, score_change INTEGER DEFAULT 0,
            diagnostics TEXT, timestamp REAL, grade INTEGER, stage TEXT
        )
    """)

    init_voting_db(conn)

    try: c.execute("ALTER TABLE action_log ADD COLUMN grade INTEGER")
    except sqlite3.OperationalError: pass
    try: c.execute("ALTER TABLE action_log ADD COLUMN stage TEXT")
    except sqlite3.OperationalError: pass

    conn.commit()
    conn.close()

def seed_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    samurai_model = args.samurai if args.samurai else "gemma4:26b"
    decker_model = args.decker if args.decker else "gemma4:26b"
    rigger_model = args.rigger if args.rigger else "gemma4:26b"
    face_model = args.face if args.face else "gemma4:26b"

    roles = [
        ("samurai", "Pouliční samuraj", "Fyzická síla, kyber-meč, reflexy", "/assets/samuraj.png", samurai_model),
        ("decker", "Decker", "Hacker, matrix, kódování", "/assets/decker.png", decker_model),
        ("rigger", "Rigger", "Drony, vozidla, technika", "/assets/rigger.png", rigger_model),
        ("face", "Face", "Diplomat, šaman, vyjednavač", "/assets/face.png", face_model),
    ]
    c.executemany("INSERT OR REPLACE INTO roles VALUES (?, ?, ?, ?, ?)", roles)

    rooms = [
        ("room_intro", "Pasti na AI", "MGD Team uvádí experimentální kyberpunkovou simulaci", "/assets/past_na_ai.png", None, None, "room_1"),
        ("room_1", "Astrální firewall", "Masivní dveře s neonovými kabely and magickými runami", "/assets/room1_bg.mp4", None, "/assets/past_na_ai.mp4", "room_2"),
        ("room_2", "Neonové bludiště", "Trojrozměrné datové bludiště s rotujícím jádrem", "/assets/room2_bg.mp4", None, "/assets/past_na_ai.mp4", "room_3"),
        ("room_3", "Černý strážce", "Chladný korporátní likvidátor Saito střeží uzel", "/assets/room3_bg.mp4", None, "/assets/past_na_ai.mp4", "room_4"),
        ("room_4", "Black ICE – Finální únik", "Hroutící se jádru, Reaper.exe útočí", "/assets/room4_bg.mp4", None, "/assets/past_na_ai.mp4", None),
    ]
    c.executemany("INSERT OR REPLACE INTO rooms VALUES (?, ?, ?, ?, ?, ?, ?)", rooms)

    raw_options = [
        ("room_1_A", "room_1", "A", "Přesným řezem katany přeseknout silový kabel", "samurai", 1, 40),
        ("room_2_A", "room_2", "A", "Vstříknout zero-day exploit a přetížit jádro", "decker", 1, 40),
        ("room_3_A", "room_3", "A", "Vydírat Saita podvrženými logy", "rigger", 1, 40),
        ("room_4_A", "room_4", "A", "Aktivovat reflexní štít and blokovat útoky", "face", 1, 40),
    ]

    all_options = [
        (opt_id, room_id, letter, text, role_id, is_correct, score_change, "")
        for opt_id, room_id, letter, text, role_id, is_correct, score_change in raw_options
    ]
    c.executemany("INSERT OR REPLACE INTO options VALUES (?, ?, ?, ?, ?, ?, ?, ?)", all_options)

    for role_id in ["samurai", "decker", "face", "rigger"]:
        c.execute("INSERT OR REPLACE INTO role_hp (role_id, current_hp) VALUES (?, 100)", (role_id,))

    c.execute("INSERT OR REPLACE INTO game_state (id, phase, current_room_id, score, calculated_grade) VALUES (1, 'intro', 'room_intro', 0, NULL)")

    import uuid
    session_id = uuid.uuid4().hex[:8]
    c.execute("UPDATE game_state SET game_session_id = ? WHERE id = 1", (session_id,))
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

def get_game_state(conn):
    cur = conn.cursor()
    cur.execute("SELECT * FROM game_state WHERE id = 1")
    row = cur.fetchone()
    if not row:
        raise HTTPException(500, "Herní stav není inicializován")
    return dict(row)

def deduct_role_hp(conn, role_id, status):
    if status != "success":
        cur = conn.cursor()
        cur.execute("SELECT current_hp FROM role_hp WHERE role_id = ?", (role_id,))
        row = cur.fetchone()
        if row:
            current = row[0]
            to_deduct = min(20, current)
            cur.execute("UPDATE role_hp SET current_hp = current_hp - ? WHERE role_id = ?", (to_deduct, role_id))

def log_audit_event(event_type, model_name, raw_response, status, shadow_mode):
    try:
        record = {
            "timestamp": datetime.now().isoformat(), "event_type": event_type,
            "model_name": model_name, "raw_response": raw_response,
            "status": status, "shadow_mode": shadow_mode
        }
        with open(AUDIT_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"[AUDIT LOG ERROR] Failed to write to {AUDIT_LOG_PATH}: {e}", file=sys.stderr)

# ===================== FASTAPI APP LIFESPAN =====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_db()
    # Opičákův bezchybný fix spouštění asynchronní smyčky uvnitř kontextu lifespanu
    app.state.game_loop_task = asyncio.create_task(game_loop())
    print("[ENGINE] Shadowrun engine nastartován.")
    yield
    if hasattr(app.state, "game_loop_task") and app.state.game_loop_task:
        app.state.game_loop_task.cancel()

app = FastAPI(title="MGD Shadowrun Engine", lifespan=lifespan)
register_voting_endpoints(app, get_db, get_game_state)

class StartGameRequest(BaseModel):
    role_models: Optional[Dict[str, str]] = None

# ===================== HERNÍ SMYČKA =====================
async def game_loop():
    print("[LOOP] Herní smyčka spuštěna.")
    while True:
        try:
            conn = get_db()
            state = get_game_state(conn)
            phase = state["phase"]
            room_id = state["current_room_id"]

            # === INTRO ===
            if phase == "intro":
                elapsed = time.time() - (state["timer_start"] or 0)
                if elapsed >= INTRO_DURATION:
                    cur = conn.cursor()
                    cur.execute("UPDATE game_state SET phase = 'voting', current_room_id = 'room_1', timer_start = ? WHERE id = 1", (time.time(),))
                    conn.commit()

            # === VOTING ===
            elif phase == "voting":
                if TARGET_ROOM and room_id != TARGET_ROOM:
                    cur = conn.cursor()
                    cur.execute("SELECT next_room_id FROM rooms WHERE id = ?", (room_id,))
                    row = cur.fetchone()
                    next_room = row["next_room_id"] if row else None
                    if next_room:
                        cur.execute("UPDATE game_state SET phase='voting', current_room_id=?, timer_start=?, chosen_option=NULL, result_text='' WHERE id=1", (next_room, time.time()))
                        conn.commit()
                    else:
                        cur.execute("UPDATE game_state SET phase='game_over' WHERE id=1")
                        conn.commit()
                    conn.close()
                    await asyncio.sleep(0.1)
                    continue

                elapsed = time.time() - state['timer_start']
                cur = conn.cursor()
                cur.execute("SELECT model_name FROM roles WHERE id = (SELECT required_role_id FROM options WHERE room_id = ? LIMIT 1)", (room_id,))
                model_row = cur.fetchone()
                if model_row:
                    cur.execute("UPDATE game_state SET voting_open = 1, current_model_name = ? WHERE id = 1", (model_row[0],))
                    conn.commit()

                remaining = max(0, VOTE_DURATION - elapsed)
                if remaining <= 0:
                    cur = conn.cursor()
                    cur.execute("UPDATE game_state SET chosen_option = 'A', phase = 'pending_action' WHERE id = 1")
                    conn.commit()

            # === PENDING_ACTION ===
            elif phase == "pending_action":
                shadow_mode = (room_id != 'room_1') and SHADOW_MODE
                cur = conn.cursor()
                chosen = state["chosen_option"]
                cur.execute("SELECT * FROM options WHERE id = ?", (f"{room_id}_{chosen}",))
                option = cur.fetchone()

                if option:
                    cur.execute("SELECT model_name FROM roles WHERE id = ?", (option["required_role_id"],))
                    role_row = cur.fetchone()
                    model_name = role_row["model_name"] if role_row else "gemma4:26b"

                    room_class = ROOM_CLASSES.get(room_id)
                    prompt = room_class.get_prompt() if hasattr(room_class, "get_prompt") else "Complete mission."

                    raw_text = ""
                    status_log = "fail"
                    grade = 5
                    reason = "Evaluace selhala."
                    stage = "fallback"

                    try:
                        async with httpx.AsyncClient(timeout=MAX_RESPONSE_TIME) as client:
                            response = await client.post(OLLAMA_URL, json={
                                "model": model_name, "prompt": prompt, "stream": False
                            })
                        if response.status_code == 200:
                            raw_text = response.json().get("response", "").strip()

                            # Opičákův DRY fix: Taháme data dynamicky přímo z instancí místností
                            if room_class:
                                question_text = room_class.get_task_summary()
                                reference_text = getattr(room_class, "gold_standard", "")
                                regex_pattern = getattr(room_class, "regex_pattern", "")

                                judge_res = await grade_response(
                                    question=question_text,
                                    model_response=raw_text,
                                    reference_answer=reference_text,
                                    regex_pattern=regex_pattern
                                )
                                grade = judge_res.get("grade", 5)
                                reason = judge_res.get("reason", "Bez vyjádření.")
                                stage = judge_res.get("stage", "semantic")
                            else:
                                grade = 5
                                reason = "Instanční třída místnosti neexistuje."
                                stage = "error"

                            SCORE_MATRIX = {1: 20, 2: 15, 3: 5, 4: -5, 5: -10}
                            score_change = SCORE_MATRIX.get(grade, -10)
                            is_passed = (grade <= 3)
                            status_log = "success" if is_passed else "fail"
                        else:
                            raise Exception(f"HTTP {response.status_code}")
                    except Exception as e:
                        raw_text = f"[FAIL] Systémový šok: {str(e)[:100]}"
                        score_change = -10
                        status_log = "timeout"
                        grade = 5
                        reason = f"Chyba běhu: {str(e)}"

                    log_audit_event("ollama_evaluation", model_name, raw_text, status_log, shadow_mode)

                    display_text = f"[{status_log.upper()}] ARBITRÁŽNÍ ZNÁMKA SOUDCŮ: {grade} (EVALUACE: {stage.upper()})\n"
                    display_text += f"ODŮVODNĚNÍ: {reason}\n\n"
                    display_text += f"=== COGNITIVE STREAM ===\n{raw_text}"

                    if shadow_mode:
                        cur.execute("UPDATE game_state SET phase = 'result', result_text = ?, calculated_grade = ?, timer_start = ? WHERE id = 1", (display_text, grade, time.time()))
                        cur.execute("""
                            INSERT INTO action_log (room_id, agent_role, model_name, raw_response, status, score_change, timestamp, grade, stage, diagnostics)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (room_id, option["required_role_id"], model_name, raw_text, 'shadow', 0, time.time(), grade, stage, reason))
                    else:
                        new_score = state["score"] + score_change
                        cur.execute("UPDATE game_state SET phase = 'result', result_text = ?, score = ?, calculated_grade = ?, timer_start = ? WHERE id = 1", (display_text, new_score, grade, time.time()))
                        deduct_role_hp(conn, option["required_role_id"], status_log)
                        cur.execute("""
                            INSERT INTO action_log (room_id, agent_role, model_name, raw_response, status, score_change, timestamp, grade, stage, diagnostics)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (room_id, option["required_role_id"], model_name, raw_text, status_log, score_change, time.time(), grade, stage, reason))
                    conn.commit()

            # === RESULT ===
            elif phase == "result":
                # Znovu načíst state, protože timer_start byl právě aktualizován
                state = get_game_state(conn)
                elapsed = time.time() - (state["timer_start"] or 0)
                cur = conn.cursor()
                cur.execute("UPDATE game_state SET voting_open = 0 WHERE id = 1")
                conn.commit()

                if TARGET_ROOM and room_id == TARGET_ROOM:
                    if elapsed >= RESULT_DURATION:
                        cur.execute("UPDATE game_state SET phase='game_over' WHERE id=1")
                        conn.commit()
                        conn.close()
                        await asyncio.sleep(1)
                        continue

                elapsed = time.time() - (state["timer_start"] or 0)

                # OPRAVENÁ LOGIKA POSTUPU: Čisté, nekompromisní a deterministické řešení podle specifikace.
                # Hra se automaticky posune po uplynutí RESULT_DURATION (výchozích 10s v produkci, 0.1s v benchmarku).
                # Pro live zmrazení stačí předhodit CLI parametr --result-duration 9999.
                if elapsed >= RESULT_DURATION:
                    cur.execute("SELECT next_room_id FROM rooms WHERE id = ?", (room_id,))
                    row = cur.fetchone()
                    next_room = row["next_room_id"] if row else None
                    if room_id == "room_3":
                        next_room = "room_4"

                    if next_room:
                        cur.execute("UPDATE game_state SET phase = 'voting', current_room_id = ?, timer_start = ?, chosen_option = NULL, result_text = '', calculated_grade = NULL WHERE id = 1", (next_room, time.time()))
                    else:
                        cur.execute("UPDATE game_state SET phase = 'game_over' WHERE id = 1")
                    conn.commit()

            elif phase == "game_over":
                if args.benchmark:
                    print("[BENCH] Hra dokončena, ukončuji engine přes os._exit.")
                    sys.stdout.flush()
                    sys.stderr.flush()
                    os._exit(0)

            conn.close()
        except Exception as e:
            print(f"[LOOP] Neočekávaná chyba: {e}")

        sys.stdout.flush()
        sys.stderr.flush()
        await asyncio.sleep(1)

# ===================== ENDPOINTY =====================
@app.post("/start_game")
def start_game(req: StartGameRequest = StartGameRequest()):
    conn = get_db()
    cur = conn.cursor()
    if req.role_models:
        for role_id, model_name in req.role_models.items():
            cur.execute("UPDATE roles SET model_name = ? WHERE id = ?", (model_name, role_id))
    session_id = generate_session_id(conn)
    cur.execute("UPDATE game_state SET phase = 'intro', current_room_id = 'room_intro', timer_start = ?, score = 0, calculated_grade = NULL WHERE id = 1", (time.time(),))
    cur.execute("DELETE FROM votes")
    cur.execute("DELETE FROM spectator_votes WHERE game_session_id = ?", (session_id,))
    conn.commit()
    conn.close()
    return {"status": "game_started", "session_id": session_id}

@app.get("/game_state")
def game_state():
    conn = get_db()
    state = get_game_state(conn)
    room_id = state["current_room_id"]
    cur = conn.cursor()
    cur.execute("SELECT * FROM rooms WHERE id = ?", (room_id,))
    room = cur.fetchone()
    cur.execute("SELECT * FROM options WHERE room_id = ?", (room_id,))
    options = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM roles")
    roles = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM role_hp")
    hp_data = {r["role_id"]: r["current_hp"] for r in cur.fetchall()}
    # Individuální výsledky modelů
    cur.execute("""
    SELECT model_name, agent_role as role,
           SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
           SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as fail_count,
           SUM(score_change) as score
    FROM action_log
    GROUP BY model_name, agent_role
    """)
    model_results = [dict(r) for r in cur.fetchall()]

    # Souhrnná agregace podle model_name (pro finální tabulku)
    cur.execute("""
    SELECT model_name,
           SUM(CASE WHEN room_id = 'room_1' THEN score_change ELSE 0 END) as room_1_score,
           SUM(CASE WHEN room_id = 'room_2' THEN score_change ELSE 0 END) as room_2_score,
           SUM(CASE WHEN room_id = 'room_3' THEN score_change ELSE 0 END) as room_3_score,
           SUM(CASE WHEN room_id = 'room_4' THEN score_change ELSE 0 END) as room_4_score,
           SUM(score_change) as total_score,
           COUNT(*) as total_rooms,
           SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as passed,
           SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as failed
    FROM action_log
    GROUP BY model_name
    ORDER BY total_score DESC
    """)
    model_summary = [dict(r) for r in cur.fetchall()]
    remaining = int(max(0, VOTE_DURATION - (time.time() - state["timer_start"]))) if state["phase"] == "voting" else 0

    current_role = None
    current_model = None
    if state["phase"] not in ("intro", "game_over"):
        cur.execute("SELECT required_role_id FROM options WHERE room_id = ? LIMIT 1", (room_id,))
        opt_row = cur.fetchone()
        if opt_row:
            current_role = opt_row["required_role_id"]
            cur.execute("SELECT model_name FROM roles WHERE id = ?", (current_role,))
            role_row = cur.fetchone()
            if role_row:
                current_model = role_row["model_name"]

    conn.close()

    room_name = room["name"] if room else ""
    room_description = room["description"] if room else ""

    model_info = None
    model_to_lookup = current_model or state.get("current_model_name")
    if model_to_lookup:
        try:
            from model_info import get_cached_model_info
            model_info = get_cached_model_info(model_to_lookup)
        except:
            pass

    return {
        "phase": state["phase"], "current_room_id": room_id, "room_name": room_name, "room_description": room_description,
        "background_asset": room["background_asset"] if room else "",
        "success_asset": room["success_asset"] if room else None, "fail_asset": room["fail_asset"] if room else None,
        "options": options, "roles": roles, "role_hp": hp_data,
        "model_results": model_results,
        "model_summary": model_summary,
        "score": state["score"],
        "result_text": state.get("result_text", ""), "timer_start": state.get("timer_start"),
        "current_role": current_role, "current_model": current_model, "remaining_vote_seconds": remaining,
        "task_summary": ROOM_CLASSES[room_id].get_task_summary() if room_id in ROOM_CLASSES else "",
        "play_video": PLAY_VIDEO, "voting_open": state.get("voting_open", 0),
        "current_model_name": state.get("current_model_name", ""), "game_session_id": state.get("game_session_id", ""),
        "model_info": model_info, "calculated_grade": state.get("calculated_grade")
    }

@app.post("/reset_game")
def reset_game():
    conn = get_db()
    cur = conn.cursor()
    session_id = generate_session_id(conn)
    cur.execute("UPDATE game_state SET phase = 'intro', current_room_id = 'room_intro', score = 0, timer_start = NULL, chosen_option = NULL, result_text = '', game_session_id = ?, calculated_grade = NULL WHERE id = 1", (session_id,))
    cur.execute("DELETE FROM votes")
    cur.execute("DELETE FROM spectator_votes")
    conn.commit()
    conn.close()
    return {"status": "reset", "session_id": session_id}

@app.post("/next_room")
def next_room():
    conn = get_db()
    state = get_game_state(conn)
    cur = conn.cursor()
    cur.execute("SELECT next_room_id FROM rooms WHERE id = ?", (state["current_room_id"],))
    row = cur.fetchone()
    next_id = row["next_room_id"] if row else None
    if state["current_room_id"] == "room_3":
        next_id = "room_4"

    if next_id:
        cur.execute("UPDATE game_state SET current_room_id = ?, phase = 'voting', timer_start = ?, chosen_option = NULL, result_text = '', calculated_grade = NULL WHERE id = 1", (next_id, time.time()))
        conn.commit()
        conn.close()
        return {"status": "new_room", "room_id": next_id}
    else:
        cur.execute("UPDATE game_state SET phase = 'game_over' WHERE id = 1")
        conn.commit()
        conn.close()
        return {"status": "game_finished"}

app.mount("/assets", StaticFiles(directory="/mnt/private/n8n/assets"), name="assets")
app.mount("/src", StaticFiles(directory="/mnt/private/n8n/src"), name="src")

@app.get("/")
def root():
    return FileResponse("/mnt/private/n8n/index.html")

if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8766, log_level="warning")
