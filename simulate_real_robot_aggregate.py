#!/usr/bin/env python3
"""Deterministic simulation of `real_polygon_cyclic_robot.py` cycle logic.

Tracks aggregate POLYGON assets:
- all wallet assets (MATIC + token mark-to-market in MATIC)
- liquidity pools of BOTH tokens (CASRS/WMATIC and CASRG/WMATIC)
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class Pair:
    token_reserve: float
    matic_reserve: float
    fee: float = 0.003

    @property
    def price(self) -> float:
        return self.matic_reserve / self.token_reserve

    def buy_token(self, matic_in: float) -> float:
        if matic_in <= 0:
            return 0.0
        eff = matic_in * (1.0 - self.fee)
        k = self.token_reserve * self.matic_reserve
        new_m = self.matic_reserve + eff
        new_t = k / new_m
        out = self.token_reserve - new_t
        self.token_reserve = new_t
        self.matic_reserve = new_m
        return out

    def sell_token(self, token_in: float) -> float:
        if token_in <= 0:
            return 0.0
        eff = token_in * (1.0 - self.fee)
        k = self.token_reserve * self.matic_reserve
        new_t = self.token_reserve + eff
        new_m = k / new_t
        out = self.matic_reserve - new_m
        self.token_reserve = new_t
        self.matic_reserve = new_m
        return out

    def add_liquidity(self, token_add: float, matic_add: float) -> None:
        self.token_reserve += max(0.0, token_add)
        self.matic_reserve += max(0.0, matic_add)


class RealRobotAggregateSim:
    def __init__(self):
        self.cfg = {
            "buy_matic": 0.03,
            "take_profit": 0.20,
            "lp_invest_matic": 0.05,
        }

        # wallet state (same 3-wallet structure as real robot)
        self.wallets: Dict[str, Dict[str, float]] = {
            "owner": {"matic": 30.0, "casrs": 0.0, "casrg": 0.0},
            "bot1": {"matic": 10.0, "casrs": 0.0, "casrg": 0.0},
            "bot2": {"matic": 10.0, "casrs": 0.0, "casrg": 0.0},
        }

        # Pools for both tokens (both required in aggregate metric)
        self.pool_rs = Pair(token_reserve=900_000.0, matic_reserve=90_000.0)
        self.pool_rg = Pair(token_reserve=500_000.0, matic_reserve=50_000.0)

        self.path: List[float] = []
        self.path_wallets: List[float] = []
        self.path_pools: List[float] = []

    def wallet_assets_matic(self) -> float:
        p_rs = self.pool_rs.price
        p_rg = self.pool_rg.price
        total = 0.0
        for w in self.wallets.values():
            total += w["matic"] + w["casrs"] * p_rs + w["casrg"] * p_rg
        return total

    def pools_assets_matic(self) -> float:
        # mark-to-market in MATIC using spot prices of each pool
        rs_val = self.pool_rs.matic_reserve + self.pool_rs.token_reserve * self.pool_rs.price
        rg_val = self.pool_rg.matic_reserve + self.pool_rg.token_reserve * self.pool_rg.price
        return rs_val + rg_val

    def aggregate_assets_matic(self) -> float:
        return self.wallet_assets_matic() + self.pools_assets_matic()

    def cycle(self) -> None:
        # 1) sequential buys with 3 wallets (CASRS)
        for name in ["owner", "bot1", "bot2"]:
            w = self.wallets[name]
            amount = min(self.cfg["buy_matic"], w["matic"])
            if amount <= 0:
                continue
            token_out = self.pool_rs.buy_token(amount)
            w["matic"] -= amount
            w["casrs"] += token_out

        # 2) sequential partial profit-taking (sell share of current CASRS)
        for name in ["owner", "bot1", "bot2"]:
            w = self.wallets[name]
            sell_amt = w["casrs"] * self.cfg["take_profit"]
            if sell_amt <= 0:
                continue
            m_out = self.pool_rs.sell_token(sell_amt)
            w["casrs"] -= sell_amt
            w["matic"] += m_out

        # 3) owner mandatory LP reinvest (same pattern as add_lp_from_owner)
        owner = self.wallets["owner"]
        invest = min(self.cfg["lp_invest_matic"], owner["matic"])
        if invest > 0:
            half = invest * 0.5
            # buy CASRS with first half
            token_got = self.pool_rs.buy_token(half)
            owner["matic"] -= half
            # add liquidity with second half + bought token
            owner["matic"] -= half
            self.pool_rs.add_liquidity(token_got, half)

    def run(self, cycles: int = 150) -> Dict:
        start_agg = self.aggregate_assets_matic()
        start_wallets = self.wallet_assets_matic()
        start_pools = self.pools_assets_matic()

        self.path = [start_agg]
        self.path_wallets = [start_wallets]
        self.path_pools = [start_pools]

        for _ in range(cycles):
            self.cycle()
            self.path.append(self.aggregate_assets_matic())
            self.path_wallets.append(self.wallet_assets_matic())
            self.path_pools.append(self.pools_assets_matic())

        end_agg = self.path[-1]
        end_wallets = self.path_wallets[-1]
        end_pools = self.path_pools[-1]

        start_rs_pool = 2.0 * 90_000.0
        start_rg_pool = 2.0 * 50_000.0

        report = {
            "cycles": cycles,
            "config": self.cfg,
            "start": {
                "aggregate_matic": start_agg,
                "wallets_matic": start_wallets,
                "pools_matic": start_pools,
                "rs_pool_matic": start_rs_pool,
                "rg_pool_matic": start_rg_pool,
            },
            "end": {
                "aggregate_matic": end_agg,
                "wallets_matic": end_wallets,
                "pools_matic": end_pools,
                "rs_pool_matic": self.pool_rs.matic_reserve + self.pool_rs.token_reserve * self.pool_rs.price,
                "rg_pool_matic": self.pool_rg.matic_reserve + self.pool_rg.token_reserve * self.pool_rg.price,
            },
            "delta": {
                "aggregate_matic": end_agg - start_agg,
                "wallets_matic": end_wallets - start_wallets,
                "pools_matic": end_pools - start_pools,
            },
            "wallets_final": self.wallets,
            "prices_final": {
                "casrs_matic": self.pool_rs.price,
                "casrg_matic": self.pool_rg.price,
            },
        }
        return report


def save_report(report: Dict) -> None:
    Path("real_robot_aggregate_150_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    s = report["start"]
    e = report["end"]
    d = report["delta"]

    md = [
        "# Aggregate assets simulation of REAL robot (150 cycles)",
        "",
        f"- Cycles: {report['cycles']}",
        "",
        "## Start",
        f"- Wallets assets: {s['wallets_matic']:.6f} MATIC",
        f"- Pools assets (RS+RG): {s['pools_matic']:.6f} MATIC",
        f"- Aggregate (wallets+pools): {s['aggregate_matic']:.6f} MATIC",
        "",
        "## End",
        f"- Wallets assets: {e['wallets_matic']:.6f} MATIC",
        f"- Pools assets (RS+RG): {e['pools_matic']:.6f} MATIC",
        f"- Aggregate (wallets+pools): {e['aggregate_matic']:.6f} MATIC",
        "",
        "## Delta",
        f"- Wallets delta: {d['wallets_matic']:.6f} MATIC",
        f"- Pools delta: {d['pools_matic']:.6f} MATIC",
        f"- Aggregate delta: {d['aggregate_matic']:.6f} MATIC",
        "",
        "## Final prices",
        f"- CASRS price: {report['prices_final']['casrs_matic']:.8f} MATIC",
        f"- CASRG price: {report['prices_final']['casrg_matic']:.8f} MATIC",
    ]
    Path("real_robot_aggregate_150_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")


if __name__ == "__main__":
    random.seed(42)
    sim = RealRobotAggregateSim()
    rep = sim.run(150)
    save_report(rep)
    print(
        "Aggregate delta:",
        f"{rep['delta']['aggregate_matic']:.6f} MATIC",
        "(wallets:",
        f"{rep['delta']['wallets_matic']:.6f}, pools: {rep['delta']['pools_matic']:.6f})",
    )
