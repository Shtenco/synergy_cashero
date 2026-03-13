#!/usr/bin/env python3
"""Deterministic simulation of existing robot logic from `sinergia_bot.py`.

Supports parameter tuning to find stable profitable regimes with LP reserve growth.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


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


class ExistingRobot150Sim:
    def __init__(
        self,
        cfg_override: Optional[Dict[str, float]] = None,
        wallets_override: Optional[Dict[str, Dict[str, float]]] = None,
        rs_pair_override: Optional[Dict[str, float]] = None,
        rg_pair_override: Optional[Dict[str, float]] = None,
    ):
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
            "bot_sell_amount": 100.0,
            "bot_sell_threshold": 200.0,
            "lp_reinvest_owner_matic": 0.0,
        }
        if cfg_override:
            self.cfg.update(cfg_override)

        self.model = {
            "h_RS": 0.50,
            "h_RG": 0.90,
            "rho": 0.10,
            "omega": 0.05,
        }

        self.wallets: Dict[str, Dict[str, float]] = wallets_override or {
            "owner": {"matic": 30.0, "casrs": 0.0, "casrg": 0.0},
            "bot1": {"matic": 10.0, "casrs": 260.0, "casrg": 240.0},
            "bot2": {"matic": 10.0, "casrs": 230.0, "casrg": 220.0},
        }

        rs = rs_pair_override or {"token_reserve": 900_000.0, "matic_reserve": 90_000.0}
        rg = rg_pair_override or {"token_reserve": 500_000.0, "matic_reserve": 50_000.0}

        self.rs_pair = Pair(token_reserve=rs["token_reserve"], matic_reserve=rs["matic_reserve"])
        self.rg_pair = Pair(token_reserve=rg["token_reserve"], matic_reserve=rg["matic_reserve"])

        self.start_rs_matic = self.rs_pair.matic_reserve
        self.start_rg_matic = self.rg_pair.matic_reserve

        self.rs_supply = 1_600_000.0
        self.rg_supply = 70_000.0
        self.price_hist: List[float] = [self.rs_pair.matic_reserve / self.rs_pair.token_reserve] * 24

        self.initial_nav = self.total_nav()
        self.nav_path: List[float] = [self.initial_nav]

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

        return {"P_spot": P_spot, "P_twap": P_twap, "P_safe": P_safe, "K": K, "STS": STS}

    def buy(self, wallet: str, token: str, matic: float):
        w = self.wallets[wallet]
        amt = min(matic, self.cfg["trade_cap_pol"], w["matic"])
        if amt <= 0:
            return
        if token == "casrs":
            out = self.rs_pair.buy_token(amt)
            w["casrs"] += out
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

    def _owner_lp_reinvest(self):
        reinvest = self.cfg["lp_reinvest_owner_matic"]
        if reinvest <= 0:
            return
        owner = self.wallets["owner"]
        amt = min(reinvest, owner["matic"])
        if amt <= 0:
            return
        half = amt * 0.5
        token_out = self.rs_pair.buy_token(half)
        owner["matic"] -= half
        # add liquidity proportionally to current price (simplified LP add)
        self.rs_pair.matic_reserve += half
        self.rs_pair.token_reserve += token_out

    def cycle(self):
        m = self.system_metrics()
        owner = self.wallets["owner"]

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
            if self.wallets[b]["casrs"] > self.cfg["bot_sell_threshold"]:
                self.sell(b, "casrs", self.cfg["bot_sell_amount"])
            if self.wallets[b]["casrg"] > self.cfg["bot_sell_threshold"]:
                self.sell(b, "casrg", self.cfg["bot_sell_amount"])

        arb_probe = min(self.cfg["arb_probe_pol"], self.cfg["trade_cap_pol"], owner["matic"])
        if arb_probe > 0.1:
            out_rs = self.rs_pair.buy_token(arb_probe)
            _ = self.rs_pair.sell_token(out_rs)

            out_rg = self.rg_pair.buy_token(arb_probe)
            _ = self.rg_pair.sell_token(out_rg)

            matic_from_rs = self.rs_pair.sell_token(out_rs)
            cross_rg = self.rg_pair.buy_token(matic_from_rs)
            _ = self.rg_pair.sell_token(cross_rg)
            _ = self.rs_pair.buy_token(matic_from_rs)

            if cross_rg > out_rg * (1 + self.cfg["arb_slippage"]):
                self.buy("owner", "casrs", arb_probe)
                rs_bal = self.wallets["owner"]["casrs"]
                self.sell("owner", "casrs", min(rs_bal, 100))

        self._owner_lp_reinvest()
        self.nav_path.append(self.total_nav())

    def run(self, cycles: int = 150):
        for _ in range(cycles):
            self.cycle()

        final_nav = self.total_nav()
        pnl = final_nav - self.initial_nav
        roi = (pnl / self.initial_nav * 100) if self.initial_nav else 0.0

        peak = self.nav_path[0]
        max_dd = 0.0
        for n in self.nav_path:
            if n > peak:
                peak = n
            dd = (peak - n) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        m = self.system_metrics()
        report = {
            "cycles": cycles,
            "config": self.cfg,
            "initial_nav_matic": self.initial_nav,
            "final_nav_matic": final_nav,
            "pnl_matic": pnl,
            "roi_pct": roi,
            "max_drawdown_pct": max_dd * 100,
            "lp_growth": {
                "rs_matic_start": self.start_rs_matic,
                "rs_matic_end": self.rs_pair.matic_reserve,
                "rs_matic_growth_pct": (self.rs_pair.matic_reserve / self.start_rs_matic - 1) * 100,
                "rg_matic_start": self.start_rg_matic,
                "rg_matic_end": self.rg_pair.matic_reserve,
                "rg_matic_growth_pct": (self.rg_pair.matic_reserve / self.start_rg_matic - 1) * 100,
            },
            "final_metrics": m,
            "wallets": self.wallets,
        }
        return report


def save_report(report: Dict, json_path: str, md_path: str):
    Path(json_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [
        "# Simulation of existing robot + existing contract mechanics",
        "",
        f"- Cycles: {report['cycles']}",
        f"- Initial NAV: {report['initial_nav_matic']:.6f} MATIC",
        f"- Final NAV: {report['final_nav_matic']:.6f} MATIC",
        f"- PnL: {report['pnl_matic']:.6f} MATIC",
        f"- ROI: {report['roi_pct']:.4f}%",
        f"- Max drawdown: {report['max_drawdown_pct']:.4f}%",
        "",
        "## LP reserve growth",
        f"- RS pool MATIC: {report['lp_growth']['rs_matic_start']:.6f} -> {report['lp_growth']['rs_matic_end']:.6f} ({report['lp_growth']['rs_matic_growth_pct']:.4f}%)",
        f"- RG pool MATIC: {report['lp_growth']['rg_matic_start']:.6f} -> {report['lp_growth']['rg_matic_end']:.6f} ({report['lp_growth']['rg_matic_growth_pct']:.4f}%)",
        "",
        "## Final metrics",
        f"- P_spot: {report['final_metrics']['P_spot']:.8f}",
        f"- P_twap: {report['final_metrics']['P_twap']:.8f}",
        f"- P_safe: {report['final_metrics']['P_safe']:.8f}",
        f"- K: {report['final_metrics']['K']:.6f}",
        f"- STS: {report['final_metrics']['STS']:.6f}",
    ]
    Path(md_path).write_text("\n".join(md) + "\n", encoding="utf-8")


if __name__ == "__main__":
    random.seed(42)
    sim = ExistingRobot150Sim()
    report = sim.run(150)
    save_report(report, "our_robot_exact_150_report.json", "our_robot_exact_150_report.md")
    print(f"PnL after 150 cycles: {report['pnl_matic']:.6f} MATIC ({report['roi_pct']:.4f}%)")
