"""
Applier-stub do spike HotStuff — faz o papel do caminho FSM → _submit_nym.

O daemon `cottonhs` entrega cada comando comitado (em ordem) via
POST /apply com o corpo = bytes do NymLogEntry. Este stub:
  - decodifica com o NymLogEntry REAL do coordinator (prova o formato);
  - registra a sequência em JSONL + hash sha256 cumulativo;
  - expõe GET /log → {"applied": n, "hash": hex} para comparar réplicas.

Servidor single-thread de propósito: preserva a ordem de chegada.
Uso: python applier_stub.py --port 24001 --out runs/x/applier-1.jsonl
"""
import argparse
import hashlib
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "coordinator"))
from log_entry import NymLogEntry  # noqa: E402


class State:
    def __init__(self, out: Path):
        self.applied = 0
        self.hash = hashlib.sha256()
        self.out = out.open("w", encoding="utf-8")


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/apply":
                self.send_error(404)
                return
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                entry = NymLogEntry.decode(data)
            except Exception as e:
                self.send_error(400, f"payload não-NYM: {e}")
                return
            state.applied += 1
            state.hash.update(data)
            state.out.write(json.dumps({
                "idx": state.applied,
                "client_id": self.headers.get("X-Client-ID"),
                "seq": self.headers.get("X-Seq"),
                "entity_id": entry.entity_id,
                "did": entry.did,
            }) + "\n")
            state.out.flush()
            self.send_response(204)
            self.end_headers()

        def do_GET(self):
            if self.path != "/log":
                self.send_error(404)
                return
            body = json.dumps({"applied": state.applied,
                               "hash": state.hash.hexdigest()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    HTTPServer(("127.0.0.1", args.port), make_handler(State(args.out))).serve_forever()


if __name__ == "__main__":
    main()
