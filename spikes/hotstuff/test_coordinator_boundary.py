"""
Teste da fronteira Go↔Python do coordinator, SEM Indy e SEM Swarm.

Sobe o que vai para a imagem: 4 processos do FastAPI real (`coordinator/main.py`)
e 4 réplicas `cottonhs`, do jeito que conviverão no container — um par por nó.
Exercita os dois sentidos com o código de produção:

    Python → Go   HotStuffClient.propose()  (coordinator/hotstuff.py)
    Go → Python   POST /apply → fsm.apply() (coordinator/main.py)

Fica de fora, de propósito, só a escrita no ledger: `fsm.apply` apenas decodifica
e enfileira — quem fala com o Indy é o `drain_queue`, que não roda aqui. Então o
teste prova ordenação, entrega e formato; NÃO prova durabilidade.

Uso:  python test_coordinator_boundary.py [--n 20]
"""
import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
COORD = HERE.parents[1] / "coordinator"
BIN = HERE / "bin" / "cottonhs"
BASE = 35000
N_REP = 4
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _env(node_num: int) -> dict:
    """Ambiente mínimo que o coordinator exige no import."""
    return {**os.environ,
            "NODE_ID": f"node-{node_num}", "NODE_NUM": str(node_num),
            "GENESIS_URL": "http://127.0.0.1:9/genesis",   # não é usado: lifespan off
            "TRUSTEE_SEED": "000000000000000000000000Trustee1",
            "TRUSTEE_DID": "V4SGRU86Z58d6TV7PBUe6f",
            "HOTSTUFF_URL": f"http://127.0.0.1:{BASE + 300 + node_num}",
            "LOG_LEVEL": "WARNING"}


def serve(node_num: int) -> None:
    """Modo servidor: roda o FastAPI real com o FSM real, sem lifespan."""
    sys.path.insert(0, str(COORD))
    import uvicorn
    import main                      # o main.py de produção
    from fsm import CoordinatorFSM
    from pending import PendingQueue

    # O lifespan (Indy, wallet, daemon) fica desligado; injetamos só o FSM,
    # que é o que o /apply toca. pool/store None: apply() não os usa.
    main.fsm = CoordinatorFSM(pool=None, store=None,
                              trustee_did=os.environ["TRUSTEE_DID"],
                              pending=PendingQueue())

    @main.app.get("/_teste/fila")            # andaime só deste teste
    def _fila():
        itens = list(main.fsm._queue.queue)
        return {"recebidos": [e.entity_id for e, _ in itens]}

    uvicorn.run(main.app, host="127.0.0.1", port=BASE + 400 + node_num,
                lifespan="off", log_level="warning")


async def main_test(n: int) -> int:
    sys.path.insert(0, str(COORD))
    from hotstuff import HotStuffClient          # cliente de produção
    from log_entry import NymLogEntry
    import httpx

    run = HERE / "runs" / time.strftime("boundary_%Y%m%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(BIN), "keygen", "-n", str(N_REP), "-dir", str(run / "cluster"),
                    "-base-port", str(BASE)], check=True)

    procs = []
    print(f"→ subindo {N_REP} coordinators (FastAPI real) e {N_REP} réplicas cottonhs")
    for i in range(1, N_REP + 1):
        procs.append(subprocess.Popen([sys.executable, __file__, "--serve", str(i)],
                                      env=_env(i),
                                      stdout=open(run / f"coord-{i}.log", "w"),
                                      stderr=subprocess.STDOUT))
    for i in range(1, N_REP + 1):
        procs.append(subprocess.Popen(
            [str(BIN), "replica", "-id", str(i), "-dir", str(run / "cluster")],
            stdout=open(run / f"replica-{i}.log", "w"), stderr=subprocess.STDOUT))

    ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            # 1. coordinators no ar
            for i in range(1, N_REP + 1):
                url = f"http://127.0.0.1:{BASE + 400 + i}/_teste/fila"
                for _ in range(100):
                    try:
                        if (await http.get(url)).status_code == 200:
                            break
                    except httpx.HTTPError:
                        await asyncio.sleep(0.2)
                else:
                    print(f"FALHA: coordinator {i} não subiu (ver {run}/coord-{i}.log)")
                    return 1

            # 2. o cliente de produção espera o daemon — mesma chamada do lifespan
            cli = HotStuffClient(f"http://127.0.0.1:{BASE + 301}")
            await cli.wait_ready(timeout=60)

            # 3. propõe NYMs reais
            rnd = lambda k: "".join(random.choices(B58, k=k))  # noqa: E731
            enviados, lat = [], []
            for k in range(n):
                e = NymLogEntry(entity_id=f"fronteira-{k:03d}", entity_type="uba",
                                did=rnd(22), verkey=rnd(44))
                t0 = time.monotonic()
                await cli.propose(e.encode())
                lat.append((time.monotonic() - t0) * 1000)
                enviados.append(e.entity_id)
            await cli.aclose()
            print(f"  {n} NYMs propostas | mediana {sorted(lat)[n // 2]:.0f} ms")

            # 4. o que cada FSM recebeu pelo /apply
            filas = {}
            for i in range(1, N_REP + 1):
                for _ in range(50):
                    r = await http.get(f"http://127.0.0.1:{BASE + 400 + i}/_teste/fila")
                    filas[i] = r.json()["recebidos"]
                    if len(filas[i]) >= n:
                        break
                    await asyncio.sleep(0.2)

        iguais = len({tuple(v) for v in filas.values()}) == 1
        completo = all(len(v) == n for v in filas.values())
        ordem_ok = filas[1] == enviados
        print()
        for i in sorted(filas):
            print(f"  coordinator {i}: {len(filas[i])}/{n} no FSM  "
                  f"primeiro={filas[i][0] if filas[i] else '—'}  "
                  f"último={filas[i][-1] if filas[i] else '—'}")
        print()
        print(f"  {'OK ' if completo else 'FALHA'} todos os 4 FSMs receberam as {n} NYMs")
        print(f"  {'OK ' if iguais else 'FALHA'} os 4 receberam na MESMA ordem")
        print(f"  {'OK ' if ordem_ok else 'FALHA'} a ordem bate com a de envio")
        print(f"\n  artefatos: {run}")
        ok = completo and iguais and ordem_ok
        return 0 if ok else 1
    finally:
        for p in procs:
            p.kill()


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve(int(sys.argv[sys.argv.index("--serve") + 1]))
    else:
        ap = argparse.ArgumentParser()
        ap.add_argument("--n", type=int, default=20)
        sys.exit(asyncio.run(main_test(ap.parse_args().n)))
