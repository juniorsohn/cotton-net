#!/usr/bin/env python3
"""
get_nym.py — Consulta um DID no ledger Indy (GET_NYM) para diagnóstico.

Mostra se o DID existe no ledger e qual o seu role — essencial para
distinguir, num registro hierárquico que falha:

  - DID ausente   → o NYM nunca commitou (ex.: rejeição de auth silenciada).
  - role != ENDORSER num pai → o pai não pode autorar o NYM do filho.

Uso (dentro da imagem do client, que já tem indy-vdr + cottontrust_core):

  docker run --rm --network host \
    -e GENESIS_URL=http://10.10.20.155:9000/genesis \
    -v /mnt/prj/g11718038933/cotton-net_2026/cotton-net/scripts:/scripts \
    localhost:5000/cottontrust-client:latest python /scripts/get_nym.py <DID> [<DID> ...]
"""
import asyncio
import json
import os
import sys

import indy_vdr
from cottontrust_core.ledger import open_pool

ROLES = {None: "IDENTITY_OWNER", "0": "TRUSTEE", "2": "STEWARD",
         "101": "ENDORSER", "201": "NETWORK_MONITOR"}


async def main() -> None:
    genesis = os.environ.get("GENESIS_URL", "http://10.10.20.155:9000/genesis")
    dids = sys.argv[1:]
    if not dids:
        sys.exit("uso: get_nym.py <DID> [<DID> ...]")

    pool = await open_pool(genesis)
    for did in dids:
        req = indy_vdr.ledger.build_get_nym_request(None, did)
        res = await pool.submit_request(req)
        result = res.get("result", res)
        data = result.get("data")
        if not data:
            print(f"❌ {did}  → AUSENTE no ledger (NYM não commitou)")
            continue
        d = json.loads(data) if isinstance(data, str) else data
        role = d.get("role")
        print(f"✅ {did}  → role={role} ({ROLES.get(role, '?')})  "
              f"verkey={d.get('verkey')}")


if __name__ == "__main__":
    asyncio.run(main())
