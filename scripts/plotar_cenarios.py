#!/usr/bin/env python3
"""
plotar_cenarios.py — Violino por CENÁRIO (não por run) da latência de transação
do COTTONTRUST (CT) vs COTTON-NET (CN), varrendo o nº de nós do ledger.

Cada violino agrega TODOS os runs de um cenário (ex.: ct_n128_run1..run10.csv),
então x = nº de nós {64,128,256,512} e, em cada nó, dois violinos: CT vs CN.
Uma curva liga as medianas de cada sistema entre os nós → tendência de escala.

Métrica (--metric): tx_time_sec por padrão, em ms, das operações de ledger
(exclui operation == 'setup_local'). Escala log (a latência é assimétrica).

  ⚠️  CUIDADO na leitura CT×CN: tx_time_sec NÃO é a mesma coisa nos dois.
      CT direto = round-trip síncrono do submit. CN coordinator =
      setup+coordinator+queue_wait+indy, ou seja INCLUI a espera na fila do FSM.
      Sob lote grande, o queue_wait do CN domina (backpressure) e infla tx_time_sec
      em ordens de grandeza — é throughput/fila, não custo de escrita por-tx.
      Para custo de escrita comparável use --metric indy_time_sec.


Descoberta de arquivos em --dir (default = RESULTS_DIR dos stacks):
  CT → ct_n{N}_run*.csv
  CN → cn_n{N}_s{S}_run*.csv     (S = --sn, default 4)

Uso:
  python3 scripts/plotar_cenarios.py \
      --dir /mnt/prj/g11718038933/cotton-net_2026/results \
      --nodes 64,128,256,512 --sn 4 --systems ct,cn

Saída: <out>/cenarios_latencia.png/.pdf   (out default = <dir>/graficos)
Requer matplotlib + numpy (stdlib para o resto).
"""
import argparse
import csv
import glob
import os
import sys

import numpy as np

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
except ImportError:
    print('Erro: matplotlib não encontrado. pip install matplotlib', file=sys.stderr)
    sys.exit(1)

# system_key -> (rótulo, cor, função-de-glob(N, S))
SYSTEMS = {
    'ct': ('CottonTrust (CT)', '#1565C0', lambda N, S: f'ct_n{N}_run*.csv'),
    'cn': ('CottonNet (CN)',   '#00897B', lambda N, S: f'cn_n{N}_s{S}_run*.csv'),
}
# coluna do CSV -> rótulo no eixo. tx_time_sec é end-to-end (ver ⚠️ no topo);
# indy_time_sec é a escrita efetiva no ledger (a métrica confiável no CN).
METRICS = {
    'consensus':            'Per-write consensus latency',
    'tx_time_sec':          'End-to-end transaction latency',
    'indy_time_sec':        'Ledger write latency (Indy)',
    'coordinator_time_sec': 'Coordinator round-trip',
    'queue_wait_sec':       'FSM queue wait',
    'setup_time_sec':       'Local setup latency',
}
# 'consensus' = comparação maçã-com-maçã CT×CN: uma escrita NYM através do pool.
#   CT: tx_time_sec (round-trip síncrono da escrita no pool flat de n nós)
#   CN: indy_time_sec (escrita no pool do SN com K_n nós, medida no coordinator)
# Nenhuma inclui a fila serial do FSM — essa aparece na decomposição
# (gen_lat_decomp.py), não aqui.
CONSENSUS_COL = {'ct': 'tx_time_sec', 'cn': 'indy_time_sec'}
MAX_POR_CENARIO = 40_000   # subamostra p/ KDE leve


def ler_latencias_ms(path, col):
    """Coluna `col` (ms) das ops de ledger de um CSV. Exclui setup_local e valores <= 0."""
    vals = []
    try:
        with open(path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row.get('operation') == 'setup_local':
                    continue
                try:
                    v = float(row.get(col, '') or 0)
                except ValueError:
                    continue
                if v > 0:
                    vals.append(v * 1000.0)
    except FileNotFoundError:
        pass
    return vals


def coletar(dir_, systems, nodes, sn, metric):
    """(sys, N) -> {'vals': np.array, 'runs': n_arquivos}. Só cenários com dados."""
    dados = {}
    for sk in systems:
        _, _, pat = SYSTEMS[sk]
        col = CONSENSUS_COL[sk] if metric == 'consensus' else metric
        for N in nodes:
            arquivos = sorted(glob.glob(os.path.join(dir_, pat(N, sn))))
            pool = []
            for a in arquivos:
                pool.extend(ler_latencias_ms(a, col))
            if pool:
                dados[(sk, N)] = {'vals': np.asarray(pool, float), 'runs': len(arquivos)}
                print(f'  {sk} n{N}: {len(arquivos)} run(s), {len(pool)} tx')
            else:
                print(f'  {sk} n{N}: (sem dados — {os.path.join(dir_, pat(N, sn))})')
    return dados


def plotar(dados, systems, nodes, out_dir, metric):
    nodes_ok = [N for N in nodes if any((sk, N) in dados for sk in systems)]
    if not nodes_ok:
        print('[ERRO] nenhum cenário com dados. Rode os *-client-10runs antes.')
        sys.exit(1)

    rng = np.random.default_rng(42)
    fig, ax = plt.subplots(figsize=(max(8, 2.4 * len(nodes_ok)), 6.8))
    n_sys = len(systems)
    largura = 0.7 / n_sys

    # medianas por sistema para as curvas de tendência (em log10 ms)
    trend = {sk: [] for sk in systems}

    for si, sk in enumerate(systems):
        rotulo, cor, _ = SYSTEMS[sk]
        off = (si - (n_sys - 1) / 2) * largura
        for xi, N in enumerate(nodes_ok):
            d = dados.get((sk, N))
            if not d:
                trend[sk].append(None)
                continue
            v = d['vals']
            if len(v) > MAX_POR_CENARIO:
                v = rng.choice(v, MAX_POR_CENARIO, replace=False)
            logv = np.log10(v)
            pos = xi + off
            parts = ax.violinplot([logv], positions=[pos], widths=largura * 0.95,
                                  showmedians=False, showextrema=False)
            for b in parts['bodies']:
                b.set_facecolor(cor)
                b.set_alpha(0.80)
                b.set_edgecolor('white')
                b.set_linewidth(0.6)
            # caixa IQR + mediana
            q1, med, q3 = np.percentile(logv, [25, 50, 75])
            ax.vlines(pos, q1, q3, color='#263238', linewidth=5, alpha=0.85)
            ax.scatter([pos], [med], color='white', s=10, zorder=4)
            trend[sk].append(med)
            # rótulo da mediana (ms) ao lado
            ha = 'right' if si == 0 else 'left'
            dx = -0.02 if si == 0 else 0.02
            ax.text(pos + dx, med, f'{10**med:.0f}', ha=ha, va='center',
                    fontsize=8, color=cor, fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.12', fc='white', ec=cor,
                              lw=0.7, alpha=0.9))

    # curvas de tendência (medianas ligadas entre nós)
    for sk in systems:
        rotulo, cor, _ = SYSTEMS[sk]
        off = (list(systems).index(sk) - (n_sys - 1) / 2) * largura
        xs = [xi + off for xi, m in enumerate(trend[sk]) if m is not None]
        ys = [m for m in trend[sk] if m is not None]
        if len(xs) >= 2:
            ax.plot(xs, ys, color=cor, linewidth=1.6, alpha=0.55, linestyle='--', zorder=3)

    # eixo Y em ms sobre escala log
    ax.yaxis.set_major_locator(mticker.FixedLocator(
        [np.log10(t) for t in (10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000)]))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f'{10**y:.0f}'))
    ax.set_ylabel(f'{METRICS[metric]} (ms) — log scale', fontsize=12)
    ax.set_xticks(range(len(nodes_ok)))
    ax.set_xticklabels([f'{N} nodes' for N in nodes_ok], fontsize=11)
    ax.set_xlabel('Ledger network size', fontsize=12)
    ax.set_title(f'{METRICS[metric]} by scenario — CT vs CN (runs pooled per scenario)',
                 fontsize=13, fontweight='bold')
    ax.yaxis.grid(True, which='major', linestyle='--', alpha=0.45)
    ax.set_axisbelow(True)

    handles = [plt.Rectangle((0, 0), 1, 1, color=SYSTEMS[sk][1], alpha=0.8,
                             label=SYSTEMS[sk][0]) for sk in systems]
    ax.legend(handles=handles, loc='upper left', framealpha=0.95,
              edgecolor='lightgray', fontsize=10)

    # nota de cobertura (nº de runs por cenário) no rodapé
    cobertura = '  '.join(
        f'{sk}n{N}={dados[(sk, N)]["runs"]}r' for sk in systems for N in nodes_ok
        if (sk, N) in dados)
    fig.text(0.99, 0.01,
             f'box = IQR + median  ·  dashed = median scaling trend  ·  runs pooled: {cobertura}',
             ha='right', va='bottom', fontsize=6.5, color='gray')

    os.makedirs(out_dir, exist_ok=True)
    fig.tight_layout()
    for ext in ('png', 'pdf'):
        p = os.path.join(out_dir, f'cenarios_latencia.{ext}')
        fig.savefig(p, dpi=150, bbox_inches='tight')
        print(f'[OK] {p}')
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description='Violino por cenário (10 runs) CT vs CN.')
    ap.add_argument('--dir', default='/mnt/prj/g11718038933/cotton-net_2026/results',
                    help='diretório com os *_run*.csv (RESULTS_DIR dos stacks)')
    ap.add_argument('--nodes', default='64,128,256,512', help='lista de nº de nós')
    ap.add_argument('--sn', default='4', help='supernodos do CN (default 4)')
    ap.add_argument('--systems', default='ct,cn', help='sistemas: ct,cn')
    ap.add_argument('--metric', default='tx_time_sec', choices=list(METRICS),
                    help='coluna do CSV a plotar (default tx_time_sec; ver ⚠️ no topo). '
                         'Para custo de escrita comparável no CN use indy_time_sec.')
    ap.add_argument('--out', default=None, help='dir de saída (default <dir>/graficos)')
    args = ap.parse_args()

    nodes = [int(x) for x in args.nodes.split(',') if x.strip()]
    systems = [s.strip() for s in args.systems.split(',') if s.strip() in SYSTEMS]
    if not systems:
        print('[ERRO] --systems inválido (use ct,cn).'); sys.exit(1)
    out_dir = args.out or os.path.join(args.dir, 'graficos')
    if args.metric == 'tx_time_sec':
        print('[INFO] tx_time_sec = latência end-to-end. No CN inclui a espera na fila do '
              'FSM, que aplica as NYMs em SÉRIE (replicação íntegra a todos os supernodos) — '
              'comportamento esperado. Para comparação CT×CN use --metric consensus.')
    if args.metric == 'consensus':
        print('[INFO] consensus = uma escrita NYM através do pool: CT usa tx_time_sec '
              '(pool flat, n nós), CN usa indy_time_sec (pool do SN, K_n nós). '
              'A fila serial do FSM fica de fora — ver gen_lat_decomp.py p/ decomposição.')

    print(f'Coletando de {args.dir} (nodes={nodes}, sn={args.sn}, '
          f'systems={systems}, metric={args.metric})')
    dados = coletar(args.dir, systems, nodes, args.sn, args.metric)
    plotar(dados, systems, nodes, out_dir, args.metric)


if __name__ == '__main__':
    main()
