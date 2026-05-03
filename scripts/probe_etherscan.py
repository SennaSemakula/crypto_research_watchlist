"""One-shot probe of the Etherscan v2 multichain endpoint.

Use to confirm field shape per chainid. Run with:

    .venv/bin/python scripts/probe_etherscan.py
"""

from __future__ import annotations

import os

import httpx

KEY = os.environ.get("ETHERSCAN_API_KEY") or ""
URL = "https://api.etherscan.io/v2/api"
CHAINS = {"ethereum": 1, "bnb": 56, "polygon": 137, "avax": 43114}


def main() -> None:
    for name, cid in CHAINS.items():
        params = {
            "chainid": str(cid),
            "module": "proxy",
            "action": "eth_blockNumber",
            "apikey": KEY,
        }
        try:
            r = httpx.get(URL, params=params, timeout=15.0)
            print(f"-- {name} (chain={cid}) -- HTTP {r.status_code}")
            print(r.text[:400])
        except Exception as exc:
            print(f"-- {name} (chain={cid}) -- ERROR: {exc}")


if __name__ == "__main__":
    main()
