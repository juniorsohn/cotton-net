#!/usr/bin/env python3
"""
gen_lat_decomp.py — Agrega TODOS os runs de cada cenário e emite as linhas
LaTeX da tabela de decomposição de latência (tab:lat_decomp do paper).

Semântica das métricas (auditada no código do client/coordinator):

  CT (mode=direto/endorsed) — 1 linha CSV por ESCRITA de ledger
  (nym_create | nym_role | attrib; setup_local é excluído):
    tx_time_sec  = round-trip síncrono da escrita no pool flat de n nós,
                   somando retries/backoffs quando houve (latência experimentada).
    coordinator/queue/indy = 0 estruturais (não existem no CT) → colunas "---".
    End-to-end ≡ Ledger write (a escrita É a transação inteira).

  CN (mode=coordinator) — 1 linha CSV por ENTIDADE (create_*):
    tx_time_sec          = setup + coordinator + queue_wait + indy (end-to-end).
    coordinator_time_sec = round-trip do propose RAFT (client → coordinator).
    queue_wait_sec       = espera na fila SERIAL do FSM (design: ordem idêntica
                           de escrita em todos os supernodos).
    indy_time_sec        = a escrita NYM no pool do SN (K_n nós), medida no
                           coordinator. Zeros do CN são medições reais (mantidos).

  Comparabilidade: a coluna "Ledger write" é 1 escrita NYM nos dois sistemas
  (CT: pool de n nós; CN: pool de K_n nós). O E2E do CT é por-escrita e o do
  CN é por-entidade — a caption da tabela deve declarar isso.

Uso:
  python3 scripts/gen_lat_decomp.py --dir <results> --nodes 64,128,192,256 --sn 4

Saída: linhas LaTeX no stdout (+ resumo com nº de runs e retries no stderr).
Stdlib apenas.
"""
import argparse
import csv
import glob
import os
import sys


def pct(v, p):
    if not v:
        return 0.0
    s = sorted(v)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100)
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def med(v):
    return pct(v, 50)


def fmt(x):
    """Segundos com precisão proporcional à magnitude."""
    if x >= 100:
        return f'{x:.0f}'
    if x >= 10:
        return f'{x:.1f}'
    if x >= 1:
        return f'{x:.2f}'
    return f'{x:.3f}'


def cell(vals):
    """'mediana (p95)' ou '---' se não há valores."""
    if not vals:
        return '---'
    return f'{fmt(med(vals))} ({fmt(pct(vals, 95))})'


def ler_rows(paths):
    rows = []
    for p in paths:
        with open(p, newline='', encoding='utf-8') as f:
            rows.extend(csv.DictReader(f))
    return rows


def f(row, col):
    try:
        return float(row.get(col, '') or 0.0)
    except ValueError:
        return 0.0


def cenario_ct(dir_, N):
    paths = sorted(glob.glob(os.path.join(dir_, f'ct_n{N}_run*.csv')))
    if not paths:
        return None
    rows = [r for r in ler_rows(paths) if r.get('operation') != 'setup_local']
    tx = [f(r, 'tx_time_sec') for r in rows if f(r, 'tx_time_sec') > 0]
    com_retry = sum(1 for r in rows if f(r, 'retries') > 0)
    return {
        'runs': len(paths), 'n_writes': len(tx),
        'e2e': tx, 'coord': [], 'queue': [], 'write': tx,
        'nota': f'{com_retry} escrita(s) com retry '
                f'({100 * com_retry / max(1, len(rows)):.2f}%)',
    }


def cenario_cn(dir_, N, S):
    paths = sorted(glob.glob(os.path.join(dir_, f'cn_n{N}_s{S}_run*.csv')))
    if not paths:
        return None
    rows = [r for r in ler_rows(paths) if r.get('mode') == 'coordinator']
    # e2e/indy > 0 (entidade sem timing do FSM não tem indy preenchido);
    # coord/queue: zeros são medições reais → mantidos.
    ok = [r for r in rows if f(r, 'indy_time_sec') > 0]
    perdidos = len(rows) - len(ok)
    return {
        'runs': len(paths), 'n_writes': len(ok),
        'e2e':   [f(r, 'tx_time_sec') for r in ok],
        'coord': [f(r, 'coordinator_time_sec') for r in ok],
        'queue': [f(r, 'queue_wait_sec') for r in ok],
        'write': [f(r, 'indy_time_sec') for r in ok],
        'nota': f'{perdidos} entidade(s) sem timing do FSM (descartadas)'
                if perdidos else 'timing do FSM completo',
    }


def main():
    ap = argparse.ArgumentParser(description='Linhas LaTeX da tab:lat_decomp.')
    ap.add_argument('--dir', default='/mnt/prj/g11718038933/cotton-net_2026/results')
    ap.add_argument('--nodes', default='64,128,192,256')
    ap.add_argument('--sn', default='4')
    args = ap.parse_args()
    nodes = [int(x) for x in args.nodes.split(',') if x.strip()]

    err = lambda *a: print(*a, file=sys.stderr)
    err(f'Agregando {args.dir} (nodes={nodes}, sn={args.sn})')
    err('Colunas: mediana (p95) em segundos, runs agrupados por cenário.\n')

    linhas_ct, linhas_cn = [], []
    for N in nodes:
        c = cenario_ct(args.dir, N)
        if c:
            err(f'  CT n{N}: {c["runs"]} run(s), {c["n_writes"]} escritas — {c["nota"]}')
            linhas_ct.append(
                f'CT $n{{=}}{N}$              & {cell(c["e2e"])} & --- & --- '
                f'& {cell(c["write"])} \\\\')
        else:
            err(f'  CT n{N}: sem CSVs (ct_n{N}_run*.csv)')
        c = cenario_cn(args.dir, N, args.sn)
        if c:
            kn = N // int(args.sn)
            err(f'  CN n{N}: {c["runs"]} run(s), {c["n_writes"]} entidades — {c["nota"]}')
            linhas_cn.append(
                f'CN $n{{=}}{N}$  ($K_n{{=}}{kn}$)  & {cell(c["e2e"])} & '
                f'{cell(c["coord"])} & {cell(c["queue"])} & {cell(c["write"])} \\\\')
        else:
            err(f'  CN n{N}: sem CSVs (cn_n{N}_s{args.sn}_run*.csv)')

    err('\n──── linhas LaTeX (colar no tabular de tab:lat_decomp) ────\n')
    for l in linhas_ct:
        print(l)
    print('\\midrule')
    for l in linhas_cn:
        print(l)


if __name__ == '__main__':
    main()
