"""Recebe produtos enviados pela extensão do Chrome (repository_dispatch 'fila_ml') e junta na fila.json."""
import json
import os
from pathlib import Path

BASE = Path(__file__).parent
FILA, HIST = BASE / "fila.json", BASE / "historico.json"
evento = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
novos = (evento.get("client_payload") or {}).get("produtos") or []
fila = json.loads(FILA.read_text(encoding="utf-8")) if FILA.exists() else []
feitos = {h["id"] for h in json.loads(HIST.read_text(encoding="utf-8"))} if HIST.exists() else set()
ids = {p["id"] for p in fila}
for p in novos:
    if p.get("id") and p.get("videos") and p["id"] not in ids and p["id"] not in feitos:
        fila.append({k: p.get(k) for k in ("id", "titulo", "link", "info", "categoria", "videos", "descricao")})
        ids.add(p["id"])
fila = [p for p in fila if p["id"] not in feitos][-40:]
FILA.write_text(json.dumps(fila, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Recebidos {len(novos)} | fila agora com {len(fila)} produtos")
