"""
Spike HotStuff × COTTON-NET — critérios de aceite (cotton-net/docs/hotstuff_integration.md §6).

  T0  regressão do conserto de liveness com pouco tráfego (patches/0002):
      T0a  com -empty-blocks=false (relab original), 1 comando isolado NUNCA comita
           (3-cadeia + off-by-one do cmdCache). Documenta o defeito.
      T0b  com bloco vazio ligado e SEM no-ops, o mesmo comando comita.
  T1  ordem + round-trip: NymLogEntry real → /propose → commit → Exec → applier Python;
      mesma sequência (hash + lista) nas 4 réplicas e nos 4 appliers.
  T2  liveness f=1: kill -9 numa réplica; comandos seguem comitando nas 3 restantes.

Pré:  (cd relab && go build -o ../bin/cottonhs ./cmd/cottonhs)
Uso:  python spike_test.py [--n-seq 60] [--n-burst 40] [--n-after-kill 40] [--filler 20ms]
"""
import argparse
import json
import random
import signal
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE / "bin" / "cottonhs"
sys.path.insert(0, str(HERE.parents[1] / "coordinator"))
from log_entry import NymLogEntry  # noqa: E402

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def http(method, url, body=None, timeout=30):
    req = urllib.request.Request(url, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw.decode(errors="replace")}


def nym(i):
    rnd = lambda n: "".join(random.choices(B58, k=n))  # noqa: E731
    return NymLogEntry(entity_id=f"spike-{i:04d}", entity_type="uba",
                       did=rnd(22), verkey=rnd(44)).encode()


def stats(xs):
    if not xs:
        return {}
    s = sorted(xs)
    return {"n": len(s), "median_ms": round(statistics.median(s), 1),
            "p95_ms": round(s[int(0.95 * (len(s) - 1))], 1), "max_ms": round(s[-1], 1)}


class Cluster:
    def __init__(self, root: Path, base_port: int, filler: str, propose_timeout: str,
                 empty_blocks: bool = True):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(BIN), "keygen", "-n", "4", "-dir", str(root / "cluster"),
                        "-base-port", str(base_port)], check=True)
        cfg = json.loads((root / "cluster" / "cluster.json").read_text())
        self.reps = {r["id"]: r for r in cfg["replicas"]}
        self.appliers, self.procs = {}, {}
        for rid, r in self.reps.items():
            port = r["applier_url"].rsplit(":", 1)[1].split("/")[0]
            self.appliers[rid] = subprocess.Popen(
                [sys.executable, str(HERE / "applier_stub.py"), "--port", port,
                 "--out", str(root / f"applier-{rid}.jsonl")])
        for rid in self.reps:
            log = open(root / f"replica-{rid}.log", "w")
            self.procs[rid] = subprocess.Popen(
                [str(BIN), "replica", "-id", str(rid), "-dir", str(root / "cluster"),
                 "-filler-interval", filler, "-propose-timeout", propose_timeout,
                 f"-empty-blocks={str(empty_blocks).lower()}"],
                stdout=log, stderr=subprocess.STDOUT)
        self._wait_ready()

    def _wait_ready(self, timeout=90):
        deadline = time.monotonic() + timeout
        pending = set(self.reps)
        while pending:
            for rid in list(pending):
                if self.procs[rid].poll() is not None:
                    tail = (self.root / f"replica-{rid}.log").read_text()[-2000:]
                    raise RuntimeError(f"réplica {rid} morreu no boot:\n{tail}")
                try:
                    if http("GET", self.url(rid, "/status"), timeout=2)[0] == 200:
                        pending.discard(rid)
                except OSError:
                    pass
            if time.monotonic() > deadline:
                raise TimeoutError(f"réplicas sem /status: {sorted(pending)}")
            time.sleep(0.3)

    def url(self, rid, path):
        return f"http://{self.reps[rid]['http_addr']}{path}"

    def status(self, rid):
        return http("GET", self.url(rid, "/status"))[1]

    def applier_log(self, rid):
        return http("GET", self.reps[rid]["applier_url"].replace("/apply", "/log"))[1]

    def propose(self, rid, data):
        t0 = time.monotonic()
        code, body = http("POST", self.url(rid, "/propose"), data, timeout=60)
        return code, body, (time.monotonic() - t0) * 1000

    def sequence(self, rid):
        with open(self.root / f"applier-{rid}.jsonl", encoding="utf-8") as f:
            return [json.loads(line)["entity_id"] for line in f]

    def wait_applied(self, rids, target, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if all(self.status(r)["applied"] >= target and
                   self.applier_log(r)["applied"] >= target for r in rids):
                return True
            time.sleep(0.2)
        return False

    def kill(self, rid):
        self.procs[rid].send_signal(signal.SIGKILL)
        self.procs[rid].wait()

    def close(self):
        for p in [*self.procs.values(), *self.appliers.values()]:
            if p.poll() is None:
                p.terminate()
        for p in [*self.procs.values(), *self.appliers.values()]:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def t0_stall(runs: Path):
    """T0a: sem o patch de bloco vazio, uma NYM isolada não comita (defeito original)."""
    c = Cluster(runs / "t0a_relab_original", 31000, "0s", "5s", empty_blocks=False)
    try:
        code, body, ms = c.propose(1, nym(0))
        time.sleep(1.0)
        applied = [c.status(r)["applied"] for r in c.reps]
        return {"PASS": code != 200 and applied == [0, 0, 0, 0],
                "propose_http": code, "propose_ms": round(ms), "body": body, "applied": applied}
    finally:
        c.close()


def t0b_blocos_vazios(runs: Path):
    """T0b: com bloco vazio e sem no-ops, a mesma NYM isolada comita nas 4 réplicas."""
    c = Cluster(runs / "t0b_bloco_vazio", 31500, "0s", "10s", empty_blocks=True)
    try:
        code, body, ms = c.propose(1, nym(0))
        convergiu = c.wait_applied(c.reps, 1, 10)
        st = {r: c.status(r) for r in c.reps}
        fillers = {r: st[r]["fillers_sent"] for r in c.reps}
        return {"PASS": (code == 200 and convergiu
                         and len({s["hash"] for s in st.values()}) == 1
                         and all(v == 0 for v in fillers.values())),
                "propose_http": code, "propose_ms": round(ms), "convergiu": convergiu,
                "applied": {r: st[r]["applied"] for r in c.reps},
                "hash_replicas_iguais": len({s["hash"] for s in st.values()}) == 1,
                "no_ops_usados": fillers, "body": body}
    finally:
        c.close()


def t1_t2(runs: Path, args):
    c = Cluster(runs / "t1_t2", 32000, args.filler, "10s")
    out = {}
    try:
        sent, codes, lat = [], [], []
        for k in range(args.n_seq):
            data = nym(len(sent))
            code, _, ms = c.propose(k % 4 + 1, data)
            sent.append(NymLogEntry.decode(data).entity_id); codes.append(code); lat.append(ms)
        seq_lat = list(lat)

        burst = [(j % 4 + 1, nym(len(sent) + j)) for j in range(args.n_burst)]
        with ThreadPoolExecutor(8) as ex:
            results = list(ex.map(lambda a: c.propose(*a), burst))
        sent += [NymLogEntry.decode(d).entity_id for _, d in burst]
        codes += [r[0] for r in results]
        burst_lat = [r[2] for r in results]

        converged = c.wait_applied(c.reps, len(sent), 30)
        st = {r: c.status(r) for r in c.reps}
        ap = {r: c.applier_log(r) for r in c.reps}
        seqs = {r: c.sequence(r) for r in c.reps}
        out["T1"] = {
            "PASS": (converged and all(x == 200 for x in codes)
                     and len({s["hash"] for s in st.values()}) == 1
                     and all(st[r]["hash"] == ap[r]["hash"] for r in c.reps)
                     and len({tuple(v) for v in seqs.values()}) == 1
                     and sorted(seqs[1]) == sorted(sent)),
            "enviados": len(sent), "http_200": codes.count(200), "convergiu": converged,
            "applied": {r: st[r]["applied"] for r in c.reps},
            "hash_replicas_iguais": len({s["hash"] for s in st.values()}) == 1,
            "hash_daemon==applier": all(st[r]["hash"] == ap[r]["hash"] for r in c.reps),
            "sequencia_appliers_identica": len({tuple(v) for v in seqs.values()}) == 1,
            "ordem_commit_difere_da_ordem_envio": seqs[1] != sent,
            "fillers_sent": {r: st[r]["fillers_sent"] for r in c.reps},
            "lat_sequencial": stats(seq_lat), "lat_rajada_8conc": stats(burst_lat),
        }

        c.kill(4)
        live = [1, 2, 3]
        codes2, lat2, base = [], [], len(sent)
        for k in range(args.n_after_kill):
            data = nym(len(sent))
            code, _, ms = c.propose(live[k % 3], data)
            sent.append(NymLogEntry.decode(data).entity_id); codes2.append(code); lat2.append(ms)
        converged2 = c.wait_applied(live, len(sent), 60)
        st2 = {r: c.status(r) for r in live}
        out["T2"] = {
            "PASS": (converged2 and all(x == 200 for x in codes2)
                     and len({s["hash"] for s in st2.values()}) == 1
                     and all(s["applied"] == len(sent) for s in st2.values())),
            "morta": 4, "enviados_pos_kill": args.n_after_kill, "http_200": codes2.count(200),
            "convergiu": converged2, "applied": {r: st2[r]["applied"] for r in live},
            "esperado": len(sent), "antes_do_kill": base,
            "hash_vivas_iguais": len({s["hash"] for s in st2.values()}) == 1,
            "lat_pos_kill": stats(lat2), "lat_pos_kill_serie_ms": [round(x) for x in lat2],
        }
        return out
    finally:
        c.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-seq", type=int, default=60)
    ap.add_argument("--n-burst", type=int, default=40)
    ap.add_argument("--n-after-kill", type=int, default=40)
    ap.add_argument("--filler", default="0s")
    ap.add_argument("--skip-t0", action="store_true")
    args = ap.parse_args()

    runs = HERE / "runs" / time.strftime("spike_%Y%m%d_%H%M%S")
    summary = {"args": vars(args)}
    if not args.skip_t0:
        summary["T0a"] = t0_stall(runs)
        print("T0a", json.dumps(summary["T0a"], ensure_ascii=False), flush=True)
        summary["T0b"] = t0b_blocos_vazios(runs)
        print("T0b", json.dumps(summary["T0b"], ensure_ascii=False), flush=True)
    summary.update(t1_t2(runs, args))
    (runs / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k != "args"}, indent=2, ensure_ascii=False))
    print(f"\nartefatos: {runs}")
    sys.exit(0 if all(summary[t]["PASS"] for t in ("T0a", "T0b", "T1", "T2") if t in summary) else 1)


if __name__ == "__main__":
    main()
