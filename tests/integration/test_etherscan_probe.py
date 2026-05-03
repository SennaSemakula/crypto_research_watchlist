"""One-off probe: hits the v2 endpoint directly per chain and prints
the raw response. Skipped without the integration marker. Use to
sanity-check chain support when adding a new chainid.
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.integration


CHAINS = {"ethereum": 1, "bnb": 56, "polygon": 137, "avax": 43114}


def test_probe_chain_responses(capsys):
    key = os.environ.get("ETHERSCAN_API_KEY")
    if not key:
        pytest.skip("ETHERSCAN_API_KEY not set")
    out_lines: list[str] = []
    for name, cid in CHAINS.items():
        params = {
            "chainid": str(cid),
            "module": "proxy",
            "action": "eth_blockNumber",
            "apikey": key,
        }
        r = httpx.get("https://api.etherscan.io/v2/api", params=params, timeout=15.0)
        out_lines.append(f"-- {name} (chain={cid}) -- HTTP {r.status_code}")
        out_lines.append(r.text[:300])
    # Print so it shows in pytest -s output.
    for line in out_lines:
        print(line)
