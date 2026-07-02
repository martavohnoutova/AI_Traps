#!/usr/bin/env python3
"""
MGD Team — Spectator Voting Backend Module.
Import do shadowrun_engine.py nebo použij samostatně.
"""

import uuid
import time
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

# ===================== DB MIGRACE =====================

VOTING_TABLES_SQL = """
-- Tabulka pro divácké hlasy
CREATE TABLE IF NOT EXISTS spectator_votes (
    game_session_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    voter_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5),
    timestamp REAL,
    PRIMARY KEY (game_session_id, voter_id, room_id, model_name)
);


"""


def init_voting_db(conn):
    """Inicializuje voting tabulky a sloupce."""
    c = conn.cursor()
    c.executescript(VOTING_TABLES_SQL)
    conn.commit()


def generate_session_id(conn) -> str:
    """Vygeneruje a uloží nový game_session_id."""
    session_id = uuid.uuid4().hex[:8]
    c = conn.cursor()
    c.execute("UPDATE game_state SET game_session_id = ? WHERE id = 1", (session_id,))
    conn.commit()
    return session_id


# ===================== PŘEVOD SKÓRE NA ZNÁMKU =====================

def model_score_to_grade(score: float) -> int:
    """Převede skóre modelu (0.0–1.0) na diváckou známku (1–5)."""
    if score >= 0.85:
        return 1
    elif score >= 0.60:
        return 2
    elif score >= 0.35:
        return 3
    elif score >= 0.05:
        return 4
    else:
        return 5


# ===================== ENDPOINTY =====================

def register_voting_endpoints(app: FastAPI, get_db, get_game_state):
    """Zaregistruje všechny voting endpointy na FastAPI aplikaci."""

    @app.get("/vote_page")
    def vote_page(
        room_id: str = Query(...),
        model_name: str = Query(...),
        session_id: str = Query(...)
    ):
        """Mobilní hlasovací stránka — známka 1–5."""
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html lang="cs">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
            <title>Hlasování</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ 
                    background: #0a0c10; color: #0ff; font-family: 'Courier New', monospace; 
                    text-align: center; padding: 10px; min-height: 100vh;
                    display: flex; flex-direction: column; justify-content: center;
                }}
                h2 {{ font-size: 5vw; margin-bottom: 5px; }}
                .info {{ font-size: 3.5vw; color: #f0f; margin: 5px 0; }}
                .scale {{ font-size: 2.5vw; color: #888; margin: 10px 0; text-align: left; padding: 0 5px; }}
                .btn-grid {{ 
                    display: grid; grid-template-columns: 1fr 1fr 1fr 1fr 1fr; 
                    gap: 8px; max-width: 400px; margin: 10px auto; 
                }}
                .vote-btn {{ 
                    font-size: 10vw; padding: 15px 5px; border: 2px solid #0ff; 
                    background: transparent; color: #0ff; border-radius: 12px; cursor: pointer; 
                }}
                .vote-btn:active {{ background: #0ff; color: #000; }}
                .vote-btn.selected {{ background: #f0f; color: #000; border-color: #f0f; }}
                #status {{ margin-top: 10px; font-size: 3.5vw; }}
                .success {{ color: #0f0; }}
                .error {{ color: #f33; }}
                #detail-link {{ font-size: 2.5vw; color: #888; margin-top: 8px; }}
            </style>
        </head>
        <body>
            <h2>HLASOVÁNÍ</h2>
            <div class="info">Místnost: {room_id}</div>
            <div class="info">Model: {model_name}</div>
            <div class="scale">
                <b>1</b> = plné řešení &nbsp;|&nbsp;
                <b>2</b> = téměř celé &nbsp;|&nbsp;
                <b>3</b> = částečně funkční<br>
                <b>4</b> = nefunkční pokus &nbsp;|&nbsp;
                <b>5</b> = od počátku špatně
            </div>
            <div class="btn-grid" id="btn-grid">
                <button class="vote-btn" onclick="vote(1)">1</button>
                <button class="vote-btn" onclick="vote(2)">2</button>
                <button class="vote-btn" onclick="vote(3)">3</button>
                <button class="vote-btn" onclick="vote(4)">4</button>
                <button class="vote-btn" onclick="vote(5)">5</button>
            </div>
            <div id="status">Vyberte známku</div>
            <div id="detail-link">Detaily na monitoru</div>
            <script>
                const VID = localStorage.getItem('vid') || (() => {{
                    const id = 'v_' + Math.random().toString(36).substr(2, 9);
                    localStorage.setItem('vid', id);
                    return id;
                }})();
                const SESSION_ID = '{session_id}';
                const ROOM_ID = '{room_id}';
                const MODEL_NAME = '{model_name}';
                let selectedScore = null;

                function vote(score) {{
                    selectedScore = score;
                    document.querySelectorAll('.vote-btn').forEach(b => b.classList.remove('selected'));
                    document.getElementById('status').textContent = 'Odesílám...';
                    document.getElementById('status').className = '';
                    
                    fetch('/cast_vote?room_id=' + ROOM_ID + 
                          '&model_name=' + encodeURIComponent(MODEL_NAME) + 
                          '&score=' + score + '&voter_id=' + VID + 
                          '&session_id=' + SESSION_ID, 
                          {{ method: 'POST' }})
                    .then(r => r.json())
                    .then(d => {{
                        if (d.status === 'ok') {{
                            document.getElementById('status').textContent = '✓ Hlas odeslán! (' + score + ')';
                            document.getElementById('status').className = 'success';
                            document.querySelectorAll('.vote-btn').forEach((b, i) => {{
                                if (i + 1 === score) b.classList.add('selected');
                            }});
                        }} else {{
                            document.getElementById('status').textContent = '✗ ' + (d.message || 'Chyba');
                            document.getElementById('status').className = 'error';
                        }}
                    }})
                    .catch(() => {{
                        document.getElementById('status').textContent = '✗ Chyba spojení';
                        document.getElementById('status').className = 'error';
                    }});
                }}

                // Pravidelně kontrolovat, zda je hlasování stále otevřené
                setInterval(() => {{
                    fetch('/game_state')
                    .then(r => r.json())
                    .then(state => {{
                        if (!state.voting_open && selectedScore) {{
                            document.getElementById('status').textContent = '🔒 Hlasování uzavřeno';
                            document.getElementById('status').className = 'error';
                        }}
                    }})
                    .catch(() => {{}});
                }}, 3000);
            </script>
        </body>
        </html>
        """)


    @app.post("/cast_vote")
    def cast_vote(
        room_id: str = Query(...),
        model_name: str = Query(...),
        score: int = Query(...),
        voter_id: str = Query(...),
        session_id: str = Query(...)
    ):
        """Zaznamená divácký hlas 1–5."""
        conn = get_db()
        state = get_game_state(conn)

        if state.get("game_session_id") != session_id:
            conn.close()
            return {"status": "error", "message": "Neplatná herní relace"}

        cur = conn.cursor()
        cur.execute("SELECT voting_open FROM game_state WHERE id = 1")
        row = cur.fetchone()
        if not row or not row[0]:
            conn.close()
            return {"status": "error", "message": "Hlasování je uzavřeno"}

        if score < 1 or score > 5:
            conn.close()
            return {"status": "error", "message": "Známka musí být 1–5"}

        cur.execute("""
            INSERT OR REPLACE INTO spectator_votes 
            (game_session_id, room_id, voter_id, model_name, score, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, room_id, voter_id, model_name, score, time.time()))

        conn.commit()
        conn.close()
        return {"status": "ok", "message": f"Hlas přijat: {score}"}


    @app.get("/spectator_results")
    def spectator_results(session_id: str = Query(...)):
        """Vrátí seřazenou tabulku diváků podle přesnosti tipování."""
        conn = get_db()
        cur = conn.cursor()

        # Získat výsledky modelů z action_log — bereme MAX skóre pro každou dvojici
        cur.execute("""
            SELECT a.room_id, a.model_name,
                   CASE 
                       WHEN a.status = 'success' THEN 1.0
                       WHEN a.status = 'timeout' THEN 0.0
                       ELSE 0.0
                   END as model_score
            FROM action_log a
        """)
        model_results = {}
        for row in cur.fetchall():
            key = (row[0], row[1])
            if key not in model_results or row[2] > model_results[key]:
                model_results[key] = row[2]

        # Spočítat odchylky pro každého diváka
        cur.execute("""
            SELECT voter_id, room_id, model_name, score 
            FROM spectator_votes 
            WHERE game_session_id = ?
        """, (session_id,))

        spectator_deltas = {}
        for row in cur.fetchall():
            voter_id = row[0]
            room_id = row[1]
            model_name = row[2]
            spectator_score = row[3]

            model_score = model_results.get((room_id, model_name), 0.0)
            model_grade = model_score_to_grade(model_score)

            delta = abs(spectator_score - model_grade)
            if voter_id not in spectator_deltas:
                spectator_deltas[voter_id] = {"total_delta": 0, "votes": 0}
            spectator_deltas[voter_id]["total_delta"] += delta
            spectator_deltas[voter_id]["votes"] += 1

        results = []
        for voter_id, data in spectator_deltas.items():
            results.append({
                "voter_id": voter_id,
                "total_delta": data["total_delta"],
                "votes": data["votes"],
                "avg_delta": round(data["total_delta"] / data["votes"], 2) if data["votes"] > 0 else 99
            })

        results.sort(key=lambda x: x["total_delta"])
        conn.close()
        return {"results": results}

    # Přidej do voting_backend.py za endpoint /spectator_results

    @app.get("/game_summary")
    def game_summary(session_id: str = Query(...)):
        """
        Vrátí kompletní sumarizaci hry:
        - Výsledky modelů (model × room, skóre, status)
        - Výsledky diváků (seřazeno podle přesnosti)
        """
        conn = get_db()
        cur = conn.cursor()

        # === 1. VÝSLEDKY MODELŮ ===
        cur.execute("""
            SELECT a.room_id, a.model_name, a.status, a.score_change,
                CASE
                    WHEN a.status = 'success' THEN 1.0
                    WHEN a.status = 'timeout' THEN 0.0
                    ELSE 0.0
                END as normalized_score
            FROM action_log a
            ORDER BY a.room_id, a.model_name
        """)

        model_results = {}
        for row in cur.fetchall():
            room_id = row[0]
            model_name = row[1]
            status = row[2]
            score_change = row[3]
            normalized_score = row[4]

            if model_name not in model_results:
                model_results[model_name] = {
                    "model_name": model_name,
                    "rooms": {},
                    "total_score": 0,
                    "passed_rooms": 0,
                    "failed_rooms": 0
                }

            model_results[model_name]["rooms"][room_id] = {
                "status": status,
                "score_change": score_change,
                "normalized_score": normalized_score,
                "grade": model_score_to_grade(normalized_score)
            }
            model_results[model_name]["total_score"] += score_change
            if status == "success":
                model_results[model_name]["passed_rooms"] += 1
            else:
                model_results[model_name]["failed_rooms"] += 1

        # Seřadit modely podle celkového skóre (nejlepší první)
        model_list = sorted(model_results.values(), key=lambda x: x["total_score"], reverse=True)

        # === 2. VÝSLEDKY DIVÁKŮ ===
        cur.execute("""
            SELECT sv.voter_id, sv.room_id, sv.model_name, sv.score,
                a.status
            FROM spectator_votes sv
            LEFT JOIN action_log a ON sv.room_id = a.room_id
                AND sv.model_name = a.model_name
            WHERE sv.game_session_id = ?
        """, (session_id,))

        # Získat skóre modelů pro převod na známku
        cur.execute("""
            SELECT a.room_id, a.model_name,
                CASE
                    WHEN a.status = 'success' THEN 1.0
                    WHEN a.status = 'timeout' THEN 0.0
                    ELSE 0.0
                END as model_score
            FROM action_log a
        """)
        model_scores = {}
        for row in cur.fetchall():
            key = (row[0], row[1])
            if key not in model_scores or row[2] > model_scores[key]:
                model_scores[key] = row[2]

        # Znovu načíst hlasy (potřebuju cursor znovu)
        cur.execute("""
            SELECT voter_id, room_id, model_name, score
            FROM spectator_votes
            WHERE game_session_id = ?
        """, (session_id,))

        spectator_deltas = {}
        spectator_details = {}
        for row in cur.fetchall():
            voter_id = row[0]
            room_id = row[1]
            model_name = row[2]
            spectator_score = row[3]

            model_score = model_scores.get((room_id, model_name), 0.0)
            model_grade = model_score_to_grade(model_score)
            delta = abs(spectator_score - model_grade)

            if voter_id not in spectator_deltas:
                spectator_deltas[voter_id] = {"total_delta": 0, "votes": 0}
                spectator_details[voter_id] = []

            spectator_deltas[voter_id]["total_delta"] += delta
            spectator_deltas[voter_id]["votes"] += 1
            spectator_details[voter_id].append({
                "room_id": room_id,
                "model_name": model_name,
                "spectator_guess": spectator_score,
                "model_actual_grade": model_grade,
                "delta": delta
            })

        spectator_list = []
        for voter_id, data in spectator_deltas.items():
            spectator_list.append({
                "voter_id": voter_id,
                "total_delta": data["total_delta"],
                "votes": data["votes"],
                "avg_delta": round(data["total_delta"] / data["votes"], 2) if data["votes"] > 0 else 99,
                "details": spectator_details.get(voter_id, [])
            })

        spectator_list.sort(key=lambda x: x["total_delta"])

        conn.close()

        return {
            "session_id": session_id,
            "models": model_list,
            "spectators": spectator_list,
            "winner": spectator_list[0] if spectator_list else None
        }


    @app.post("/open_voting")
    def open_voting(room_id: str = Query(...), model_name: str = Query(...)):
        """Otevře hlasování pro danou místnost a model."""
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE game_state 
            SET voting_open = 1, current_room_id = ?, current_model_name = ? 
            WHERE id = 1
        """, (room_id, model_name))
        conn.commit()
        conn.close()
        return {"status": "ok"}


    @app.post("/close_voting")
    def close_voting():
        """Uzavře hlasování."""
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE game_state SET voting_open = 0 WHERE id = 1")
        conn.commit()
        conn.close()
        return {"status": "ok"}


# ===================== INTEGRAČNÍ FUNKCE =====================

def patch_shadowrun_engine(engine_path: str = "/mnt/private/n8n/shadowrun_engine.py"):
    """
    Aplikuje potřebné změny do shadowrun_engine.py:
    - Import voting modulu
    - Registrace endpointů
    - Inicializace voting DB
    - Otevírání/zavírání hlasování v herní smyčce
    - game_session_id do /game_state
    """
    print("[VOTING] Pro integraci do shadowrun_engine.py přidej ručně:")
    print("  1. from voting_backend import *")
    print("  2. Do init_db(): init_voting_db(conn)")
    print("  3. Do start_game(): generate_session_id(conn)")
    print("  4. Do lifespan/startup: register_voting_endpoints(app, get_db, get_game_state)")
    print("  5. Do /game_state: přidej 'game_session_id', 'voting_open', 'current_model_name'")
    print("  6. V herní smyčce volej open_voting() při vstupu do voting fáze")
    print("  7. V herní smyčce volej close_voting() při vstupu do result fáze")


if __name__ == "__main__":
    patch_shadowrun_engine()
