#!/usr/bin/env python3
"""
Analisador de métricas pós-rodada do COTTON-NET / COTTONTRUST.

Processa o CSV gerado pelo MetricsCollector (client/metrics/collector.py) e
emite um relatório com latência por-transação, por-operação, por-tipo de
entidade (agrupando por entity_id), throughput e percentis. Detecta modo
coordinator (CN) e decompõe coordinator/queue_wait/indy quando presente.

Sem dependências externas (stdlib). Funciona para CT (direto/endorsed) e CN.

Uso:
    python3 scripts/analyze_metrics.py client/output/ct_n128_run1.csv
    python3 scripts/analyze_metrics.py <csv> --md relatorio.md   # também escreve markdown
"""
import argparse
import csv
import statistics as st
from collections import defaultdict
from datetime import datetime


def pct(values, p):
    """Percentil p (0-100) por interpolação linear; values não precisa estar ordenado."""
    if not values:
        return 0.0
    v = sorted(values)
    if len(v) == 1:
        return v[0]
    k = (len(v) - 1) * (p / 100)
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def stat_row(label, v):
    n = len(v)
    return (f"{label:<14} n={n:<5} média={st.mean(v):7.3f}s  mediana={st.median(v):7.3f}s  "
            f"p95={pct(v,95):7.3f}s  p99={pct(v,99):7.3f}s  "
            f"min={min(v):6.3f}s  max={max(v):7.3f}s  desv={(st.pstdev(v) if n>1 else 0):6.3f}s")


def parse_ts(s):
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--md", help="caminho opcional para também salvar relatório em markdown")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.csv, encoding="utf-8")))
    if not rows:
        print("CSV vazio."); return

    def f(r, k): return float(r.get(k, 0) or 0)

    L = []
    def out(s=""):
        L.append(s); print(s)

    # Janela / throughput (wall-clock)
    ts = [t for t in (parse_ts(r["timestamp"]) for r in rows) if t]
    wall = (max(ts) - min(ts)).total_seconds() if len(ts) > 1 else 0.0
    is_cn = any((r.get("mode") == "coordinator") or f(r, "indy_time_sec") > 0 for r in rows)

    out("=" * 100)
    out(f"ANÁLISE DE MÉTRICAS — {args.csv}")
    out(f"sistema: {'COTTON-NET (coordinator/CN)' if is_cn else 'COTTONTRUST (direto/endorsed/CT)'}")
    out("=" * 100)
    out(f"transações (linhas) : {len(rows)}")
    out(f"janela              : {min(ts)}  →  {max(ts)}")
    out(f"wall-clock          : {wall:,.1f}s  ({wall/3600:.2f}h)")

    # Entidades (group-by entity_id) = unidade de negócio
    by_eid = defaultdict(list)
    for r in rows:
        if r.get("entity_id"):
            by_eid[r["entity_id"]].append(r)
    n_ent = len(by_eid)
    out(f"entidades (entity_id): {n_ent}")
    if wall > 0:
        out(f"throughput          : {len(rows)/wall:.3f} tx/s   |   {n_ent/wall:.3f} entidades/s   (1 worker, serial)")

    # ── Latência por TRANSAÇÃO (separando escritas de ledger do setup_local) ──
    ledger_ops = [r for r in rows if r["operation"] != "setup_local"]
    T = [f(r, "tx_time_sec") for r in ledger_ops]
    out("\n— LATÊNCIA POR ESCRITA NO LEDGER (exclui setup_local) —")
    if T: out("  " + stat_row("GLOBAL", T))

    out("\n— Por operação —")
    byop = defaultdict(list)
    for r in rows: byop[r["operation"]].append(f(r, "tx_time_sec"))
    for op in sorted(byop, key=lambda k: -len(byop[k])):
        out("  " + stat_row(op, byop[op]))

    out("\n— Por modo —")
    bymode = defaultdict(list)
    for r in ledger_ops: bymode[r.get("mode", "?")].append(f(r, "tx_time_sec"))
    for m in sorted(bymode, key=lambda k: -len(bymode[k])):
        out("  " + stat_row(m, bymode[m]))

    # ── Latência por ENTIDADE (soma das ops de cada entity_id) = registro E2E ──
    out("\n— LATÊNCIA POR ENTIDADE (soma das escritas de cada entity_id) —")
    by_type_total = defaultdict(list)
    type_of = {}
    for eid, ops in by_eid.items():
        total = sum(f(r, "tx_time_sec") for r in ops)
        et = next((r["entity_type"] for r in ops if r.get("entity_type")), "?")
        type_of[eid] = et
        by_type_total[et].append(total)
    allent = [t for v in by_type_total.values() for t in v]
    if allent: out("  " + stat_row("GLOBAL", allent))
    order = ["entidade", "fazenda", "setor", "talhao", "lote_mp", "fardinho", "uba", "armazem", "bale"]
    for et in [x for x in order if x in by_type_total] + [x for x in by_type_total if x not in order]:
        out("  " + stat_row(et, by_type_total[et]))

    # ── Decomposição CN ──
    if is_cn:
        out("\n— DECOMPOSIÇÃO DE TEMPO (modo coordinator) —")
        for col in ("coordinator_time_sec", "queue_wait_sec", "indy_time_sec", "setup_time_sec"):
            v = [f(r, col) for r in rows if f(r, col) > 0]
            if v: out("  " + stat_row(col, v))

    # ── Payload, retries ──
    sizes = [int(float(r.get("tx_size_bytes", 0) or 0)) for r in rows]
    nz = [s for s in sizes if s > 0]
    if nz:
        out(f"\nPayload (size>0): n={len(nz)} média={st.mean(nz):.0f}B "
            f"min={min(nz)}B max={max(nz)}B soma={sum(nz):,}B")
    retr = [int(float(r.get("retries", 0) or 0)) for r in rows]
    if any(retr):
        out(f"Retries: total={sum(retr)} máx={max(retr)} linhas_com_retry={sum(1 for x in retr if x>0)}")
    else:
        out("Retries: 0 (nenhum retry read-after-write)")
    out("=" * 100)

    if args.md:
        with open(args.md, "w", encoding="utf-8") as fo:
            fo.write("```\n" + "\n".join(L) + "\n```\n")
        print(f"\n[markdown salvo em {args.md}]")


if __name__ == "__main__":
    main()
