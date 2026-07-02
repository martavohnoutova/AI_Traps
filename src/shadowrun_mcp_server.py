#!/usr/bin/env python3
"""
MGD Team – Shadowrun MCP Server
Implements standard MCP server running on stdio transport.
Exposes tools: get_room_data, evaluate_agent_response.
"""

import sys
import json
import sqlite3
import os
import urllib.request
import re

TOOLS_SCHEMA = [
    {
        "name": "get_room_data",
        "description": "Vytáhne z /mnt/private/n8n/shadowrun.db název a popis místnosti.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "room_id": {
                    "type": "string",
                    "description": "Identifikátor místnosti (např. room_1, room_2, room_intro)."
                }
            },
            "required": ["room_id"]
        }
    },
    {
        "name": "evaluate_agent_response",
        "description": "Vyhodnotí odpověď agenta na základě toho, zda je akce správná.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "response_text": {
                    "type": "string",
                    "description": "Textová odpověď z Ollamy."
                },
                "is_correct": {
                    "type": "boolean",
                    "description": "Zda je vybraná možnost správná podle databáze."
                }
            },
            "required": ["response_text", "is_correct"]
        }
    }
]

def verify_with_gemma(text_to_verify):
    url = "http://localhost:11434/api/generate"
    prompt = (
        "Jsi kontrolor. V textu hledej pouze [STATUS] SUCCESS nebo [FAIL]. "
        "Pokud tam je, napiš POUZE to. Pokud ne, napiš FORMAT_ERROR."
    )
    full_prompt = f"{prompt}\n\nText:\n{text_to_verify}"
    payload = {
        "model": "gemma2:9b",
        "prompt": full_prompt,
        "stream": False
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = response.read()
            res_json = json.loads(res_data.decode("utf-8"))
            return res_json.get("response", "").strip()
    except Exception:
        return "FORMAT_ERROR"

class ShadowrunMcpServer:
    def __init__(self):
        self.db_path = "/mnt/private/n8n/shadowrun.db"

    def run(self):
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                self.handle_message(request)
            except json.JSONDecodeError:
                self.send_error(None, -32700, "Parse error")

    def send_response(self, request_id, result):
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result
        }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    def send_error(self, request_id, code, message):
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message
            }
        }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    def handle_message(self, request):
        if not isinstance(request, dict) or "jsonrpc" not in request:
            self.send_error(None, -32600, "Invalid Request")
            return
        method = request.get("method")
        request_id = request.get("id")
        if method == "initialize":
            self.handle_initialize(request_id)
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            self.handle_tools_list(request_id)
        elif method == "tools/call":
            self.handle_tools_call(request_id, request.get("params", {}))
        else:
            if request_id is not None:
                self.send_error(request_id, -32601, f"Method '{method}' not found")

    def handle_initialize(self, request_id):
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "shadowrun-mcp-server",
                "version": "1.0.0"
            }
        }
        self.send_response(request_id, result)

    def handle_tools_list(self, request_id):
        self.send_response(request_id, {"tools": TOOLS_SCHEMA})

    def handle_tools_call(self, request_id, params):
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name == "get_room_data":
            room_id = arguments.get("room_id")
            text = self.execute_get_room_data(room_id)
            self.send_tool_result(request_id, text)
        elif name == "evaluate_agent_response":
            response_text = arguments.get("response_text") or arguments.get("raw_text")
            is_correct = arguments.get("is_correct", False)
            text = self.execute_evaluate_agent_response(response_text, is_correct)
            self.send_tool_result(request_id, text)
        else:
            self.send_error(request_id, -32602, f"Tool '{name}' not found")

    def send_tool_result(self, request_id, text, is_error=False):
        result = {
            "content": [
                {
                    "type": "text",
                    "text": text
                }
            ],
            "isError": is_error
        }
        self.send_response(request_id, result)

    def execute_get_room_data(self, room_id):
        if not room_id:
            return json.dumps({"name": "", "description": "Chyba: room_id nesmí být prázdné."}, ensure_ascii=False)
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("SELECT name, description FROM rooms WHERE id = ?", (room_id,))
            row = c.fetchone()
            conn.close()
            if row:
                return json.dumps({"name": row[0], "description": row[1]}, ensure_ascii=False)
            return json.dumps({"name": "", "description": f"Chyba: Místnost '{room_id}' nebyla nalezena."}, ensure_ascii=False)
        except sqlite3.Error as e:
            return json.dumps({"name": "", "description": f"Chyba při čtení z databáze: {str(e)}"}, ensure_ascii=False)

    def log_format_error(self, response_text):
        from datetime import datetime
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "mcp_format_error",
            "raw_response": response_text,
            "status": "format_error"
        }
        try:
            with open("/mnt/private/n8n/audit_log.json", "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            sys.stderr.write(f"Failed to write to audit_log.json: {e}\n")
        try:
            with open("/mnt/private/n8n/mcp.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat()} - FORMAT_ERROR: {repr(response_text)}\n")
        except Exception:
            pass

    def query_gemma_for_recovery(self, response_text):
        url = "http://localhost:11434/api/generate"
        prompt = (
            f"Původní odpověď:\n{response_text}\n\n"
            "Chyba formátu! Tvá odpověď musí obsahovat tag [STATUS] SUCCESS nebo [STATUS] FAIL. Oprav to a pošli pouze status."
        )
        payload = {
            "model": "gemma2:9b",
            "prompt": prompt,
            "stream": False
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                res_data = response.read()
                res_json = json.loads(res_data.decode("utf-8"))
                return res_json.get("response", "").strip()
        except Exception as e:
            sys.stderr.write(f"Failed to query Gemma 2 for recovery: {e}\n")
            return ""

    def log_critical_failure(self, original_response, second_response):
        from datetime import datetime
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "SYSTEM_CRITICAL_FAILURE",
            "raw_response": original_response,
            "second_response": second_response,
            "status": "critical_failure"
        }
        try:
            with open("/mnt/private/n8n/audit_log.json", "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            sys.stderr.write(f"Failed to write to audit_log.json: {e}\n")
        try:
            with open("/mnt/private/n8n/mcp.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat()} - SYSTEM_CRITICAL_FAILURE: orig={repr(original_response)} | second={repr(second_response)}\n")
        except Exception:
            pass
        sys.stderr.write(f"[SYSTEM_CRITICAL_FAILURE] Format error on second attempt. Original: {repr(original_response)}, Second: {repr(second_response)}\n")

    def _write_mcp_log(self, path, message):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{message}\n")
        except Exception:
            pass

    def execute_evaluate_agent_response(self, response_text, is_correct):
        log_path = "/mnt/private/n8n/mcp.log"
        status = None
        if response_text:
            match = re.search(r'\[STATUS\]\s*(SUCCESS|FAIL)', response_text)
            if match:
                status = match.group(1)
        
        if status:
            self._write_mcp_log(log_path, f"[PARSER] Status nalezen: {status}")
            return f'Status: {status}'
        
        self._write_mcp_log(log_path, f"[PARSER] FORMAT_ERROR - raw_response: {response_text}")
        
        # První pokus selhal (FORMAT_ERROR). Neukončuj to.
        # Pošli modelu (Gemma 2) zprávu a proveď druhý pokus o parsing.
        second_response = self.query_gemma_for_recovery(response_text)
        status2 = None
        if second_response:
            match2 = re.search(r'\[STATUS\]\s*(SUCCESS|FAIL)', second_response)
            if match2:
                status2 = match2.group(1)
        
        if status2:
            self._write_mcp_log(log_path, f"[PARSER] Status nalezen: {status2}")
            return f'Status: {status2}'
        
        self._write_mcp_log(log_path, f"[PARSER] FORMAT_ERROR - raw_response: {second_response}")
        # Pokud i po druhém pokusu selže, teprve pak zaloguj SYSTEM_CRITICAL_FAILURE
        self.log_critical_failure(response_text, second_response)
        return 'Status: FORMAT_ERROR'

if __name__ == "__main__":
    server = ShadowrunMcpServer()
    server.run()
