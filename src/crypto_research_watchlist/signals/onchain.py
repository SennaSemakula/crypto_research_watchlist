"""On-chain activity signal.

v1 supports two inputs (provided via SignalContext):
  * active_addresses_z — z-score of 30d active address count vs 1y baseline
  * exchange_netflow_usd_7d — net USD flowing INTO exchanges over 7d
    (negative = outflow = bullish accumulation)

Returns NEUTRAL when neither input is available. The data provider
that fills these fields (Blockchair / Etherscan) is stubbed in v1.
"""

from __future__ import annotations

from . import SignalContext, SignalResult, label_from_strength


def evaluate(ctx: SignalContext) -> SignalResult:
    z = ctx.active_addresses_z
    netflow = ctx.exchange_netflow_usd_7d
    if z is None and netflow is None:
        return SignalResult(source="onchain", details={"reason": "no on-chain data"})

    bullets: list[str] = []
    components: list[float] = []
    details: dict = {}

    if z is not None:
        details["active_addresses_z"] = round(z, 2)
        if z >= 2.0:
            components.append(0.5)
            bullets.append(f"Active-address z-score {z:.1f}: unusually high on-chain activity")
        elif z >= 1.0:
            components.append(0.25)
            bullets.append(f"Active-address z-score {z:.1f}: elevated on-chain activity")
        elif z <= -1.0:
            components.append(-0.25)
            bullets.append(f"Active-address z-score {z:.1f}: subdued on-chain activity")

    if netflow is not None:
        details["exchange_netflow_usd_7d"] = int(netflow)
        # Strong outflow (large negative) => accumulation => bullish.
        if netflow <= -1e8:
            components.append(0.4)
            bullets.append(f"Exchange netflow {-netflow / 1e6:.0f}M USD outflow over 7d: accumulation")
        elif netflow <= -2.5e7:
            components.append(0.2)
            bullets.append(f"Exchange netflow {-netflow / 1e6:.0f}M USD outflow over 7d")
        elif netflow >= 1e8:
            components.append(-0.4)
            bullets.append(f"Exchange netflow {netflow / 1e6:.0f}M USD inflow over 7d: distribution")
        elif netflow >= 2.5e7:
            components.append(-0.2)
            bullets.append(f"Exchange netflow {netflow / 1e6:.0f}M USD inflow over 7d")

    strength = max(-1.0, min(1.0, sum(components)))
    return SignalResult(
        source="onchain",
        strength=strength,
        label=label_from_strength(strength),
        bullets=bullets,
        details=details,
    )
