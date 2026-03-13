#!/usr/bin/env python3
"""Deterministic 150-cycle simulation of *existing* robot logic from `sinergia_bot.py`.

Goal: emulate current bot rules and contract-style metrics offline (no RPC),
so we can measure concrete profit/loss over 150 cycles.
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

    def quote_out(self, amount_in: float, path_len: int = 2) -> float:
        if path_len != 2:
            raise ValueError("pair quote supports 2-step only")
        eff = amount_in * (1.0 - self.fee)
        k = self.token_reserve * self.matic_reserve
        new_m = self.matic_reserve + eff
        new_t = k / new_m
        return self.token_reserve - new_t


class ExistingRobot150Sim:
    def __init__(self):
        self.cfg = {
            "trade_cap_pol": 5.0,
            "buyback_pol": 1.0,
            "rebalance_pol": 1.0,
            "repay_fraction": 0.5,
            "rebalance_thresh": 0.02,
            "k_buyback": 1.3,
            "sts_buyback": 1.1,
            "k_repay": 1.15,
            "arb_slippage": 0.01,
            "arb_probe_pol": 0.5,
        }
        self.model = {
            "h_RS": 0.50,
            "h_RG": 0.90,
            "rho": 0.10,
            "omega": 0.05,
        }

        self.wallets: Dict[str, Dict[str, float]] = {
            "owner": {"matic": 30.0, "casrs": 0.0, "casrg": 0.0},
            "bot1": {"matic": 10.0, "casrs": 260.0, "casrg": 240.0},
            "bot2": {"matic": 10.0, "casrs": 230.0, "casrg": 220.0},
        }

        # Approximate current market depths (to represent deployed pools)
        self.rs_pair = Pair(token_reserve=900_000.0, matic_reserve=90_000.0)
        self.rg_pair = Pair(token_reserve=500_000.0, matic_reserve=50_000.0)

        self.rs_supply = 1_600_000.0
        self.rg_supply = 70_000.0
        self.price_hist: List[float] = [self.rs_pair.matic_reserve / self.rs_pair.token_reserve] * 24

        self.initial_nav = self.total_nav()

    def total_nav(self) -> float:
        p_rs = self.rs_pair.matic_reserve / self.rs_pair.token_reserve
        p_rg = self.rg_pair.matic_reserve / self.rg_pair.token_reserve
        nav = 0.0
        for w in self.wallets.values():
            nav += w["matic"] + w["casrs"] * p_rs + w["casrg"] * p_rg
        return nav

    def system_metrics(self):
        X = self.rs_pair.token_reserve
        Y = self.rs_pair.matic_reserve
        P_spot = Y / X
        self.price_hist.pop(0)
        self.price_hist.append(P_spot)
        P_twap = sum(self.price_hist) / len(self.price_hist)

        F = self.rs_supply
        x_stress = self.model["rho"] * F
        lv = Y - (X * Y) / (X + x_stress * (1 - 0.003))
        p_exit = lv / x_stress if x_stress > 0 else P_spot
        P_safe = min(P_twap, p_exit)

        B = Y
        C = X
        R_RS = X / 2
        R_RG = self.rg_pair.token_reserve
        D = self.rg_supply

        A = B + (1 - self.model["h_RS"]) * C * P_safe + (1 - self.model["h_RS"]) * R_RS * P_safe + self.model["h_RG"] * R_RG
        unwind = self.model["omega"] * D
        K = (A - unwind) / D if D > 0 else 99.0
        numerator = B + lv + (1 - self.model["h_RS"]) * C * P_safe + self.model["h_RG"] * R_RG
        denominator = D + unwind
        STS = numerator / denominator if denominator > 0 else 99.0

        return {
            "P_spot": P_spot,
            "P_twap": P_twap,
            "P_safe": P_safe,
            "K": K,
            "STS": STS,
        }

    def buy(self, wallet: str, token: str, matic: float):
        w = self.wallets[wallet]
        amt = min(matic, self.cfg["trade_cap_pol"], w["matic"])
        if amt <= 0:
            return
        if token == "casrs":
            out = self.rs_pair.buy_token(amt)
            w["casrs"] += out
            self.rs_supply += 0.0
        else:
            out = self.rg_pair.buy_token(amt)
            w["casrg"] += out
        w["matic"] -= amt

    def sell(self, wallet: str, token: str, amount: float):
        w = self.wallets[wallet]
        if token == "casrs":
            amt = min(amount, w["casrs"])
            if amt <= 0:
                return
            out = self.rs_pair.sell_token(amt)
            w["casrs"] -= amt
            w["matic"] += out
        else:
            amt = min(amount, w["casrg"])
            if amt <= 0:
                return
            out = self.rg_pair.sell_token(amt)
            w["casrg"] -= amt
            w["matic"] += out

    def repay(self, wallet: str, amount_rg: float):
        w = self.wallets[wallet]
        amt = min(amount_rg, w["casrg"])
        if amt <= 0:
            return
        w["casrg"] -= amt
        self.rg_supply = max(0.0, self.rg_supply - amt)

    def cycle(self):
        m = self.system_metrics()
        owner = self.wallets["owner"]

        # copied logic from sinergia_bot.strategy_step
        if m["K"] > self.cfg["k_buyback"] and m["STS"] > self.cfg["sts_buyback"] and owner["matic"] > self.cfg["buyback_pol"]:
            self.buy("owner", "casrs", self.cfg["buyback_pol"])

        if m["K"] < self.cfg["k_repay"] and owner["casrg"] > 10:
            repay_amt = min(owner["casrg"] * self.cfg["repay_fraction"], 50)
            self.repay("owner", repay_amt)

        if owner["matic"] > self.cfg["rebalance_pol"]:
            if m["P_spot"] > m["P_twap"] * (1 + self.cfg["rebalance_thresh"]):
                self.buy("owner", "casrg", self.cfg["rebalance_pol"])
            elif m["P_spot"] < m["P_twap"] * (1 - self.cfg["rebalance_thresh"]):
                self.buy("owner", "casrs", self.cfg["rebalance_pol"])

        for b in ("bot1", "bot2"):
            if self.wallets[b]["casrs"] > 200:
                self.sell(b, "casrs", 100)
            if self.wallets[b]["casrg"] > 200:
                self.sell(b, "casrg", 100)

        # emulate arb probe from sinergia_bot (same intent, simplified quote check)
        arb_probe = min(self.cfg["arb_probe_pol"], self.cfg["trade_cap_pol"], owner["matic"])
        if arb_probe > 0.1:
            # WMATIC->RS output
            out_rs = self.rs_pair.buy_token(arb_probe)
            # undo virtual trade effect by reversing approximately to keep probe as quote-only
            _ = self.rs_pair.sell_token(out_rs)

            # WMATIC->RG output
            out_rg = self.rg_pair.buy_token(arb_probe)
            _ = self.rg_pair.sell_token(out_rg)

            # RS->WMATIC->RG cross approximate
            matic_from_rs = self.rs_pair.sell_token(out_rs)
            cross_rg = self.rg_pair.buy_token(matic_from_rs)
            # revert
            _ = self.rg_pair.sell_token(cross_rg)
            _ = self.rs_pair.buy_token(matic_from_rs)

            if cross_rg > out_rg * (1 + self.cfg["arb_slippage"]):
                self.buy("owner", "casrs", arb_probe)
                rs_bal = self.wallets["owner"]["casrs"]
                self.sell("owner", "casrs", min(rs_bal, 100))

    def run(self, cycles: int = 150):
        for _ in range(cycles):
            self.cycle()

        final_nav = self.total_nav()
        pnl = final_nav - self.initial_nav
        roi = (pnl / self.initial_nav * 100) if self.initial_nav else 0.0

        m = self.system_metrics()
        report = {
            "cycles": cycles,
            "initial_nav_matic": self.initial_nav,
            "final_nav_matic": final_nav,
            "pnl_matic": pnl,
            "roi_pct": roi,
            "final_metrics": m,
            "wallets": self.wallets,
            "pool_rs": {
                "token_reserve": self.rs_pair.token_reserve,
                "matic_reserve": self.rs_pair.matic_reserve,
            },
            "pool_rg": {
                "token_reserve": self.rg_pair.token_reserve,
                "matic_reserve": self.rg_pair.matic_reserve,
            },
        }
        Path("our_robot_exact_150_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md = [
            "# Simulation of existing robot + existing contract mechanics (150 cycles)",
            "",
            f"- Cycles: {cycles}",
            f"- Initial NAV: {self.initial_nav:.6f} MATIC",
            f"- Final NAV: {final_nav:.6f} MATIC",
            f"- PnL: {pnl:.6f} MATIC",
            f"- ROI: {roi:.4f}%",
            "",
            "## Final system metrics",
            f"- P_spot: {m['P_spot']:.8f}",
            f"- P_twap: {m['P_twap']:.8f}",
            f"- P_safe: {m['P_safe']:.8f}",
            f"- K: {m['K']:.6f}",
            f"- STS: {m['STS']:.6f}",
        ]
        Path("our_robot_exact_150_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        print(f"PnL after {cycles} cycles: {pnl:.6f} MATIC ({roi:.4f}%)")


if __name__ == "__main__":
    random.seed(42)
    sim = ExistingRobot150Sim()
    sim.run(150)
