#!/usr/bin/env python3
"""
subset_load.py — Gera um subconjunto representativo da carga real COTTONTRUST.

A carga real é dominada por fardinhos (~186k) e lotes_mp (~28k). Para um
smoke-test "em escala" (mas que termine em tempo razoável) recortamos uma
fração de lotes_mp e fardinhos, mantendo INTACTOS todos os níveis superiores
(entidades, fazendas, setores, talhões, armazéns).

Por que manter os níveis superiores inteiros?
  A cadeia de endorsers é:
      setor   -> id_fazenda  (fazenda)
      talhão  -> id_setor    (setor)
      lote_mp -> id_armazem  (armazém)
      fardinho-> id_armazem  (armazém)
  Mantendo todos os armazéns/setores/talhões/fazendas, qualquer lote/fardinho
  amostrado continua tendo um endorser válido no ledger — preserva a
  integridade referencial sem nenhum esforço de "join" no recorte.

Uso:
    python3 scripts/subset_load.py \
        --src /mnt/prj/g11718038933/cotton-net_2026/data \
        --dst /mnt/prj/g11718038933/cotton-net_2026/data-subset \
        --fardinhos 2000 --lotes 500 --seed 42

Saída: 7 arquivos JSON em --dst (entidades, fazendas, setores, talhoes,
armazens, lotes_mp, fardinhos), prontos para montar via DATA_DIR.
"""
import argparse
import json
import random
import sys
from pathlib import Path

# Níveis mantidos integralmente (pequenos e raízes da cadeia de endorsers).
FULL_LEVELS = ["entidades", "fazendas", "setores", "talhoes", "armazens"]
# Níveis amostrados (volume).
SAMPLED_LEVELS = ["lotes_mp", "fardinhos"]


def load(path: Path) -> list:
    if not path.exists():
        sys.exit(f"❌ Arquivo ausente: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig").strip() or "[]")
    if not isinstance(data, list):
        sys.exit(f"❌ Esperava lista em {path}, veio {type(data).__name__}")
    return data


def sample(items: list, n: int, rng: random.Random) -> list:
    if n <= 0 or n >= len(items):
        return items
    return rng.sample(items, n)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path, help="Diretório da carga real")
    ap.add_argument("--dst", required=True, type=Path, help="Diretório de saída do subconjunto")
    ap.add_argument("--fardinhos", type=int, default=2000, help="Qtd de fardinhos (0 = todos)")
    ap.add_argument("--lotes", type=int, default=500, help="Qtd de lotes_mp (0 = todos)")
    ap.add_argument("--seed", type=int, default=42, help="Semente (reprodutibilidade)")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    args.dst.mkdir(parents=True, exist_ok=True)

    targets = {"lotes_mp": args.lotes, "fardinhos": args.fardinhos}
    total = 0

    print(f"Origem:  {args.src}")
    print(f"Destino: {args.dst}")
    print(f"Semente: {args.seed}\n")
    print(f"{'nível':<12}{'original':>10}{'subconjunto':>14}")
    print("-" * 36)

    for lvl in FULL_LEVELS + SAMPLED_LEVELS:
        items = load(args.src / f"{lvl}.json")
        if lvl in targets:
            out = sample(items, targets[lvl], rng)
        else:
            out = items  # mantém integralmente
        (args.dst / f"{lvl}.json").write_text(
            json.dumps(out, ensure_ascii=False), encoding="utf-8"
        )
        total += len(out)
        print(f"{lvl:<12}{len(items):>10}{len(out):>14}")

    print("-" * 36)
    print(f"{'TOTAL NYMs':<12}{'':>10}{total:>14}")

    # ── Validação de integridade referencial ─────────────────────────────────
    # Confirma que cada registro amostrado tem um endorser presente no recorte.
    # Se algum falhar, o client cai para o trustee (descaracteriza a carga).
    print("\nIntegridade referencial (endorser presente no subconjunto):")
    ids = lambda lvl: {str(r["id"]) for r in load(args.dst / f"{lvl}.json")}
    faz, setr, arm = ids("fazendas"), ids("setores"), ids("armazens")

    def check(lvl: str, field: str, ref: set) -> None:
        rows = load(args.dst / f"{lvl}.json")
        miss = sum(1 for r in rows if str(r.get(field) or "") not in ref)
        ok = len(rows) - miss
        flag = "✅" if miss == 0 else f"⚠️  {miss} fallback→trustee"
        print(f"  {lvl+' -> '+field:<26} {ok}/{len(rows)} {flag}")

    check("setores", "id_fazenda", faz)
    check("talhoes", "id_setor", setr)
    check("lotes_mp", "id_armazem", arm)
    check("fardinhos", "id_armazem", arm)

    print(f"\n✅ Subconjunto escrito em {args.dst}")
    print(f"   Deploy: DATA_DIR={args.dst} make ct-deploy")


if __name__ == "__main__":
    main()
