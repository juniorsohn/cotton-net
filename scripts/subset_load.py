#!/usr/bin/env python3
"""
subset_load.py — Gera um subconjunto da carga real COTTONTRUST respeitando a
cadeia de endorsers (todo registro amostrado mantém um endorser válido no
recorte, sem cair no fallback do trustee).

Cadeia de endorsers (pai -> filho):
    fazenda  -> setor    (setor.id_fazenda)
    setor    -> talhao   (talhao.id_setor)
    armazem  -> lote_mp  (lote.id_armazem)
    armazem  -> fardinho (fardinho.id_armazem)
  entidades, fazendas e armazens sao endossados pelo trustee.
  Observacao: lote_mp tambem carrega `id_talhao`, mas como DADO — o endorser
  do lote e o armazem. Reduzir talhoes nao quebra o registro dos lotes.

Amostragem TOP-DOWN com CASCATA (preserva os endorsers):
  --setores N    amostra N setores; talhoes cujo setor sumiu sao descartados
  --talhoes N    amostra N talhoes (FOLHA — nada e endossado por talhao)
  --armazens N   amostra N armazens; lotes/fardinhos orfaos sao descartados
  --lotes N      amostra N lotes_mp   (dentre os de armazem sobrevivente)
  --fardinhos N  amostra N fardinhos  (idem)
  0 = mantem todos daquele nivel. Entidades e fazendas (3 cada, raiz da
  cadeia) sao sempre mantidas integralmente.

Uso:
    python3 scripts/subset_load.py --src <dir> --dst <dir> \
        [--setores N] [--talhoes N] [--armazens N] [--lotes N] [--fardinhos N] [--seed S]

    # ex.: recorte pequeno E rapido (corta tambem setor/talhao, os endorsed lentos)
    python3 scripts/subset_load.py --src .../data --dst .../data-mini \
        --setores 20 --talhoes 40 --armazens 15 --lotes 40 --fardinhos 80

Saida: 7 JSONs em --dst, prontos para montar via DATA_DIR.
"""
import argparse
import json
import random
import sys
from pathlib import Path


def load(path: Path) -> list:
    if not path.exists():
        sys.exit(f"❌ Arquivo ausente: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig").strip() or "[]")
    if not isinstance(data, list):
        sys.exit(f"❌ Esperava lista em {path}, veio {type(data).__name__}")
    return data


def sample(items: list, n: int, rng: random.Random) -> list:
    """Amostra n itens (n <= 0 ou n >= len -> mantem todos)."""
    if n <= 0 or n >= len(items):
        return items
    return rng.sample(items, n)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path, help="Diretório da carga real")
    ap.add_argument("--dst", required=True, type=Path, help="Diretório de saída do subconjunto")
    ap.add_argument("--setores",   type=int, default=0, help="Qtd de setores (0=todos; cascata em talhões)")
    ap.add_argument("--talhoes",   type=int, default=0, help="Qtd de talhões (0=todos; folha)")
    ap.add_argument("--armazens",  type=int, default=0, help="Qtd de armazéns (0=todos; cascata em lotes/fardinhos)")
    ap.add_argument("--lotes",     type=int, default=500,  help="Qtd de lotes_mp (0=todos)")
    ap.add_argument("--fardinhos", type=int, default=2000, help="Qtd de fardinhos (0=todos)")
    ap.add_argument("--seed",      type=int, default=42, help="Semente (reprodutibilidade)")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    args.dst.mkdir(parents=True, exist_ok=True)
    sid = lambda r: str(r.get("id") or "")

    # ── Carrega ────────────────────────────────────────────────────────────────
    entidades     = load(args.src / "entidades.json")
    fazendas      = load(args.src / "fazendas.json")
    setores_all   = load(args.src / "setores.json")
    talhoes_all   = load(args.src / "talhoes.json")
    armazens_all  = load(args.src / "armazens.json")
    lotes_all     = load(args.src / "lotes_mp.json")
    fardinhos_all = load(args.src / "fardinhos.json")

    # ── Amostra top-down, cascateando para não órfãos de endorser ──────────────
    setores = sample(setores_all, args.setores, rng)
    keep_setor = {sid(s) for s in setores}

    talhoes_validos = [t for t in talhoes_all if str(t.get("id_setor") or "") in keep_setor]
    talhoes = sample(talhoes_validos, args.talhoes, rng)

    armazens = sample(armazens_all, args.armazens, rng)
    keep_arm = {sid(a) for a in armazens}

    lotes_validos = [l for l in lotes_all if str(l.get("id_armazem") or "") in keep_arm]
    lotes = sample(lotes_validos, args.lotes, rng)

    fardinhos_validos = [f for f in fardinhos_all if str(f.get("id_armazem") or "") in keep_arm]
    fardinhos = sample(fardinhos_validos, args.fardinhos, rng)

    # ── Escreve + tabela ───────────────────────────────────────────────────────
    saidas = [
        ("entidades", entidades,     entidades),
        ("fazendas",  fazendas,      fazendas),
        ("setores",   setores_all,   setores),
        ("talhoes",   talhoes_all,   talhoes),
        ("armazens",  armazens_all,  armazens),
        ("lotes_mp",  lotes_all,     lotes),
        ("fardinhos", fardinhos_all, fardinhos),
    ]
    print(f"Origem:  {args.src}")
    print(f"Destino: {args.dst}")
    print(f"Semente: {args.seed}\n")
    print(f"{'nível':<12}{'original':>10}{'subconjunto':>14}")
    print("-" * 36)
    total = 0
    for lvl, orig, out in saidas:
        (args.dst / f"{lvl}.json").write_text(
            json.dumps(out, ensure_ascii=False), encoding="utf-8")
        total += len(out)
        print(f"{lvl:<12}{len(orig):>10}{len(out):>14}")
    print("-" * 36)
    print(f"{'TOTAL NYMs':<12}{'':>10}{total:>14}")

    # ── Integridade referencial (endorser presente no recorte) ─────────────────
    print("\nIntegridade referencial (endorser presente no subconjunto):")
    faz = {sid(r) for r in fazendas}

    def check(nome: str, rows: list, field: str, ref: set) -> None:
        miss = sum(1 for r in rows if str(r.get(field) or "") not in ref)
        flag = "✅" if miss == 0 else f"⚠️  {miss} fallback→trustee"
        print(f"  {nome + ' -> ' + field:<26} {len(rows) - miss}/{len(rows)} {flag}")

    check("setores",   setores,   "id_fazenda",  faz)
    check("talhoes",   talhoes,   "id_setor",    keep_setor)
    check("lotes_mp",  lotes,     "id_armazem",  keep_arm)
    check("fardinhos", fardinhos, "id_armazem",  keep_arm)

    print(f"\n✅ Subconjunto escrito em {args.dst}")
    print(f"   Deploy: DATA_DIR={args.dst} make ct-deploy")


if __name__ == "__main__":
    main()
