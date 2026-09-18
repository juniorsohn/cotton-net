"""
Helper do demo do spike HotStuff. Os scripts .sh chamam os subcomandos daqui.

Tudo que ele faz é: falar HTTP com as réplicas (/propose, /status), falar com os
appliers Python (/log) e imprimir tabela. Nenhuma mágica — leia à vontade.
"""
import argparse
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
sys.path.insert(0, str(SPIKE.parents[1] / "coordinator"))
from log_entry import NymLogEntry  # noqa: E402

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
RUN = HERE / ".run"


def cluster():
    cfg = json.loads((RUN / "cluster" / "cluster.json").read_text())
    return {r["id"]: r for r in cfg["replicas"]}


def get(url, timeout=2):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def status(rep):
    try:
        return get(f"http://{rep['http_addr']}/status")
    except (OSError, ValueError):
        return None


def applier(rep):
    try:
        return get(rep["applier_url"].replace("/apply", "/log"))
    except (OSError, ValueError):
        return None


def make_nym(entity_id):
    r = lambda n: "".join(random.choices(B58, k=n))  # noqa: E731
    return NymLogEntry(entity_id=entity_id, entity_type="uba", did=r(22), verkey=r(44))


def propose(rep, data, timeout=30):
    req = urllib.request.Request(f"http://{rep['http_addr']}/propose", data=data, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}"), (time.monotonic() - t0) * 1000
    except urllib.error.HTTPError as e:
        return e.code, {"raw": e.read().decode(errors="replace")}, (time.monotonic() - t0) * 1000
    except OSError as e:
        return 0, {"erro": str(e)}, (time.monotonic() - t0) * 1000


def cmd_table(_args):
    reps = cluster()
    st = {i: status(r) for i, r in reps.items()}
    ap = {i: applier(r) for i, r in reps.items()}
    vivas = [i for i in reps if st[i]]
    print(f"  {'réplica':<9}{'estado':<10}{'aplicadas':<11}{'hash (12)':<14}{'pendentes':<11}{'no-ops':<8}")
    for i in sorted(reps):
        if not st[i]:
            print(f"  {i:<9}{'MORTA':<10}{'—':<11}{'—':<14}{'—':<11}{'—':<8}")
            continue
        s = st[i]
        print(f"  {i:<9}{'viva':<10}{s['applied']:<11}{s['hash'][:12]:<14}"
              f"{s['pending']:<11}{s['fillers_sent']:<8}")
    if not vivas:
        print("\n  nenhuma réplica no ar — rode ./01_up.sh")
        return 1
    hashes = {st[i]["hash"] for i in vivas}
    ok_h = len(hashes) == 1
    ok_a = all(ap[i] and ap[i]["hash"] == st[i]["hash"] for i in vivas)
    print(f"\n  {'OK ' if ok_h else 'FALHA'} hash idêntico nas {len(vivas)} réplicas vivas"
          f"  → todas executaram a MESMA sequência, na mesma ordem")
    print(f"  {'OK ' if ok_a else 'FALHA'} hash do daemon Go == hash do applier Python"
          f"  → a fronteira Go→Python não perdeu nem reordenou nada")
    return 0 if (ok_h and ok_a) else 1


def cmd_nym(args):
    reps = cluster()
    rid = args.replica
    entry = make_nym(args.entity_id)
    data = entry.encode()
    print(f"→ propondo NYM entity_id={entry.entity_id!r} did={entry.did} na réplica {rid}")
    print(f"  ({len(data)} bytes de NymLogEntry real, o mesmo formato do coordinator)\n")
    code, body, ms = propose(reps[rid], data)
    print(f"  HTTP {code} em {ms:.0f} ms   {json.dumps(body, ensure_ascii=False)}\n")
    time.sleep(0.4)
    rc = cmd_table(args)
    print("\n  última linha de cada applier Python (o que chegaria no Indy):")
    for i in sorted(reps):
        f = RUN / f"applier-{i}.jsonl"
        linhas = f.read_text().splitlines() if f.exists() else []
        print(f"    applier-{i}: {linhas[-1] if linhas else '(vazio)'}")
    return rc if code == 200 else 1


def cmd_lote(args):
    reps = cluster()
    vivas = sorted(i for i, r in reps.items() if status(r))
    base = status(reps[vivas[0]])["applied"]
    print(f"→ propondo {args.n} NYMs, alternando entre as réplicas vivas {vivas}\n")
    lat, codes, enviados = [], [], []
    for k in range(args.n):
        rid = vivas[k % len(vivas)]
        entry = make_nym(f"{args.prefixo}-{k:03d}")
        code, _, ms = propose(reps[rid], entry.encode())
        lat.append(ms); codes.append(code); enviados.append(entry.entity_id)
        print(f"  [{k+1:>3}/{args.n}] réplica {rid}  {entry.entity_id:<16} HTTP {code}  {ms:6.0f} ms")
    ok = codes.count(200)
    print(f"\n  {ok}/{args.n} comitadas   mediana {statistics.median(lat):.0f} ms   "
          f"máx {max(lat):.0f} ms\n")
    alvo = base + ok
    for _ in range(100):
        if all((status(reps[i]) or {}).get("applied", -1) >= alvo for i in vivas):
            break
        time.sleep(0.2)
    rc = cmd_table(args)
    seqs = {}
    for i in vivas:
        f = RUN / f"applier-{i}.jsonl"
        seqs[i] = [json.loads(l)["entity_id"] for l in f.read_text().splitlines()]
    iguais = len({tuple(v) for v in seqs.values()}) == 1
    print(f"\n  {'OK ' if iguais else 'FALHA'} os {len(vivas)} appliers gravaram a MESMA sequência de entity_id")
    fora = [e for e in enviados if e not in seqs[vivas[0]]]
    print(f"  {'OK ' if not fora else 'FALHA'} todas as NYMs enviadas aparecem no log "
          f"({len(fora)} faltando)")
    ordem = seqs[vivas[0]][-ok:] != enviados[:ok] if ok else False
    print(f"  nota: a ordem de commit {'DIFERE' if ordem else 'coincide com'} a ordem de envio "
          f"— quem decide a ordem é o consenso, não o cliente")
    return rc if ok == args.n and iguais and not fora else 1


def cmd_esperar(args):
    reps = cluster()
    alvo = time.monotonic() + args.timeout
    while time.monotonic() < alvo:
        if all(status(r) for r in reps.values()):
            return 0
        time.sleep(0.3)
    return 1


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("table")
    n = sub.add_parser("nym"); n.add_argument("entity_id"); n.add_argument("--replica", type=int, default=1)
    l = sub.add_parser("lote"); l.add_argument("n", type=int); l.add_argument("--prefixo", default="lote")
    e = sub.add_parser("esperar"); e.add_argument("--timeout", type=float, default=60)
    args = p.parse_args()
    sys.exit({"table": cmd_table, "nym": cmd_nym, "lote": cmd_lote, "esperar": cmd_esperar}[args.cmd](args))


if __name__ == "__main__":
    main()
