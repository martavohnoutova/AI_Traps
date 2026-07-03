#!/usr/bin/env python3
"""
MGD Team — Dynamic Model Info Resolver.
No hardcoded data. Sources: Ollama API → Gemma4 via subprocess → DB cache.
Final working version.
"""

import subprocess
import json
import sqlite3
import re
import time
import asyncio
import traceback

DB_PATH = "/mnt/private/n8n/model_cache.db"
INFO_MODEL = "gemma4:26b"
CACHE_TTL = 86400  # 24 hodin

INFO_PROMPT = """You are a technical AI model analyst. Given the technical specifications
of an AI model, write a SHORT description (2-3 sentences) covering:
1. What this model is generally good at
2. Its typical weaknesses or limitations

Be specific and honest. Do NOT write marketing fluff.
Output as plain text, not JSON. First sentence: strengths. Second sentence: weaknesses.

Model specs:
"""


def _connect_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_model_info_table():
    conn = _connect_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS model_info (
            model_name TEXT PRIMARY KEY,
            architecture TEXT,
            parameters TEXT,
            context_length INTEGER,
            quantization TEXT,
            capabilities TEXT,
            strengths TEXT,
            weaknesses TEXT,
            generated_at REAL
        )
    """)
    conn.commit()
    conn.close()


def get_ollama_model_data(model_name: str) -> dict | None:
    try:
        result = subprocess.run(
            ['ollama', 'show', model_name],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None

        output = result.stdout
        data = {}

        arch_match = re.search(r'architecture\s+(\S+)', output)
        if arch_match:
            data['architecture'] = arch_match.group(1)

        params_match = re.search(r'parameters\s+([\d.]+\s*[BM])', output)
        if params_match:
            data['parameters'] = params_match.group(1).replace(' ', '')

        ctx_match = re.search(r'context length\s+(\d+)', output)
        if ctx_match:
            data['context_length'] = int(ctx_match.group(1))

        quant_match = re.search(r'quantization\s+(\S+)', output)
        if quant_match:
            data['quantization'] = quant_match.group(1)

        caps_section = re.search(r'Capabilities\n(.*?)(?:\n\s*\n|\Z)', output, re.DOTALL)
        if caps_section:
            caps = [c for c in re.findall(r'\S+', caps_section.group(1)) if c]
            if caps:
                data['capabilities'] = ', '.join(caps)

        return data if data else None
    except Exception as e:
        print(f"[MODEL_INFO] Error: ollama show {model_name}: {e}")
        return None


def get_cached_model_info(model_name: str) -> dict | None:
    conn = _connect_db()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM model_info WHERE model_name = ? AND generated_at > ?",
        (model_name, time.time() - CACHE_TTL)
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def save_model_info(model_name: str, ollama_data: dict, strengths: str, weaknesses: str, generated_at: float | None = None):
    if generated_at is None:
        generated_at = time.time()
    conn = _connect_db()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO model_info
        (model_name, architecture, parameters, context_length, quantization,
         capabilities, strengths, weaknesses, generated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        model_name,
        ollama_data.get('architecture', ''),
        ollama_data.get('parameters', ''),
        ollama_data.get('context_length', 0),
        ollama_data.get('quantization', ''),
        ollama_data.get('capabilities', ''),
        strengths,
        weaknesses,
        generated_at
    ))
    conn.commit()
    conn.close()


def generate_model_description_sync(model_name: str, ollama_data: dict) -> tuple[str, str, bool]:
    """Use ollama run via subprocess — bypasses HTTP API issues with thinking tokens."""
    specs_text = "\n".join(f"- {k}: {v}" for k, v in ollama_data.items())
    prompt = INFO_PROMPT + specs_text

    try:
        result = subprocess.run(
            ['ollama', 'run', INFO_MODEL],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300
        )
        raw = result.stdout.strip()

        if not raw:
            print(f"[MODEL_INFO] Empty response for {model_name}")
            return fallback(ollama_data)

        print(f"[MODEL_INFO] Got {len(raw)} chars for {model_name}")

        # Odstran thinking proces — řádky začínající * nebo mezera* nebo - *
        # Najdi konec thinking procesu — "done thinking." nebo "...done thinking."
        done_marker = re.search(r'\.\.\.done thinking\.|done thinking\.', raw)
        if done_marker:
            # Všechno za markerem je odpověď
            clean_text = raw[done_marker.end():].strip()
            clean_text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', clean_text)
        else:
            # Fallback: odstraň řádky začínající * (thinking)
            lines = raw.split('\n')
            response_lines = []
            in_thinking = True
            for line in lines:
                stripped = line.strip()
                if in_thinking and (stripped.startswith('*') or stripped.startswith('- *') or stripped.startswith('-*')):
                    continue
                elif stripped and not stripped.startswith('*') and not stripped.startswith('-'):
                    in_thinking = False
                    response_lines.append(line)
                elif not in_thinking:
                    response_lines.append(line)
            clean_text = ' '.join(response_lines).strip()

        # Parsuj věty z clean_text
        sentences = [s.strip() for s in clean_text.replace('\n', ' ').split('.') if len(s.strip()) > 20]

        if len(sentences) >= 2:
            strengths = sentences[0] + '.'
            weaknesses = sentences[1] + '.'
            return strengths, weaknesses, True
        elif len(sentences) == 1:
            return sentences[0] + '.', '', True
        else:
            # Fallback: použij prvních 300 znaků clean_text
            return clean_text[:300], '', True

    except subprocess.TimeoutExpired:
        print(f"[MODEL_INFO] Timeout for {model_name}")
    except Exception as e:
        print(f"[MODEL_INFO] Subprocess error for {model_name}: {e}")

    return fallback(ollama_data)

def fallback(ollama_data: dict) -> tuple[str, str, bool]:
    arch = ollama_data.get('architecture', 'unknown')
    params = ollama_data.get('parameters', 'unknown')
    return (
        f"Model with {arch} architecture, {params} parameters.",
        "No detailed analysis available.",
        False
    )


async def get_model_info(model_name: str) -> dict:
    init_model_info_table()

    cached = get_cached_model_info(model_name)
    if cached and cached.get('strengths') and 'No detailed analysis' not in cached.get('strengths', ''):
        return cached

    ollama_data = get_ollama_model_data(model_name)
    if not ollama_data:
        ollama_data = {
            'architecture': 'unknown',
            'parameters': 'unknown',
            'context_length': 0,
            'quantization': 'unknown',
            'capabilities': 'unknown'
        }

    strengths, weaknesses, is_valid = generate_model_description_sync(model_name, ollama_data)
    save_model_info(model_name, ollama_data, strengths, weaknesses, generated_at=time.time() if is_valid else 0)

    return {
        'model_name': model_name,
        'architecture': ollama_data.get('architecture', ''),
        'parameters': ollama_data.get('parameters', ''),
        'context_length': ollama_data.get('context_length', 0),
        'quantization': ollama_data.get('quantization', ''),
        'capabilities': ollama_data.get('capabilities', ''),
        'strengths': strengths,
        'weaknesses': weaknesses
    }


def get_display_name(model_name: str) -> str:
    mapping = {
        'gemma4': 'Gemma 4',
        'gemma2': 'Gemma 2',
        'mistral-large': 'Mistral Large',
        'mistral': 'Mistral',
        'llama3.1': 'Llama 3.1',
        'llama3': 'Llama 3',
        'qwen2.5': 'Qwen 2.5',
        'qwen-coder': 'Qwen Coder',
        'deepseek-coder': 'DeepSeek Coder',
        'phi4': 'Phi-4',
    }
    for key in sorted(mapping, key=len, reverse=True):
        if model_name.startswith(key):
            return mapping[key]
    return model_name.split(':')[0].replace('-', ' ').title()


def refresh_all_models():
    try:
        result = subprocess.run(['ollama', 'list'], capture_output=True, text=True, timeout=10)
        models = []
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('NAME'):
                continue
            parts = line.split()
            if parts:
                models.append(parts[0])

        init_model_info_table()

        for model in models:
            print(f"  🔍 Processing {model}...")
            try:
                asyncio.run(get_model_info(model))
            except Exception as inner_e:
                print(f"    ⚠️ Failed for {model}: {inner_e}")

        print(f"  ✅ Finished. Processed {len(models)} models.")
        return models
    except Exception as e:
        print(f"[MODEL_INFO] Error refreshing: {e}")
        traceback.print_exc()
        return []


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MGD Model Info Resolver")
    parser.add_argument("--refresh", action="store_true", help="Refresh cache for all models")
    parser.add_argument("--show", type=str, help="Show info for a specific model")

    args = parser.parse_args()

    if args.refresh:
        refresh_all_models()
    elif args.show:
        async def show():
            info = await get_model_info(args.show)
            print(json.dumps(info, indent=2, ensure_ascii=False))
        asyncio.run(show())
    else:
        print("Usage: python3 model_info.py --refresh | --show <model>")
