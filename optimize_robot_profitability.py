#!/usr/bin/env python3
"""Grid search for stable profitable settings on existing robot simulation."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from simulate_our_robot_150 import ExistingRobot150Sim


def score(r: dict) -> float:
    return (
        r["pnl_matic"] * 1000
        + r["lp_growth"]["rs_matic_growth_pct"] * 25
        + r["lp_growth"]["rg_matic_growth_pct"] * 25
        - r["max_drawdown_pct"] * 200
    )


def main() -> None:
    buyback_vals = [0.1, 0.2, 0.4, 0.6, 0.8, 1.0]
    rebalance_vals = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    arb_probe_vals = [0.0, 0.1, 0.2, 0.3]
    bot_sell_vals = [20.0, 40.0, 60.0, 80.0, 100.0]
    bot_threshold_vals = [200.0, 260.0, 320.0, 400.0, 600.0]
    lp_reinvest_vals = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10]

    all_runs = []
    feasible = []
    for buyback, rebalance, arb_probe, bot_sell, bot_thr, lp_re in itertools.product(
        buyback_vals, rebalance_vals, arb_probe_vals, bot_sell_vals, bot_threshold_vals, lp_reinvest_vals
    ):
        cfg = {
            "buyback_pol": buyback,
            "rebalance_pol": rebalance,
            "arb_probe_pol": arb_probe,
            "bot_sell_amount": bot_sell,
            "bot_sell_threshold": bot_thr,
            "lp_reinvest_owner_matic": lp_re,
        }
        sim = ExistingRobot150Sim(cfg_override=cfg)
        rep = sim.run(150)
        rep["fitness"] = score(rep)
        all_runs.append(rep)

        if (
            rep["pnl_matic"] > 0
            and rep["lp_growth"]["rs_matic_growth_pct"] > 0
            and rep["lp_growth"]["rg_matic_growth_pct"] > 0
            and rep["max_drawdown_pct"] <= 1.0
        ):
            feasible.append(rep)

    all_runs.sort(key=lambda x: x["fitness"], reverse=True)
    feasible.sort(key=lambda x: x["fitness"], reverse=True)

    Path("robot_param_search_top10_any.json").write_text(
        json.dumps(all_runs[:10], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path("robot_param_search_top10_feasible.json").write_text(
        json.dumps(feasible[:10], ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = ["# Robot parameter search (150 cycles)", ""]
    lines.append(f"- Total runs: {len(all_runs)}")
    lines.append(f"- Fully feasible runs (profit + both LP up + DD<=1%): {len(feasible)}")
    lines.append("")

    lines.append("## Top-10 by fitness (any)")
    lines.append("")
    for i, t in enumerate(all_runs[:10], 1):
        c = t["config"]
        lines.extend([
            f"### {i}",
            f"- pnl: {t['pnl_matic']:.6f} MATIC; roi: {t['roi_pct']:.4f}%; dd: {t['max_drawdown_pct']:.4f}%",
            f"- lp rs: {t['lp_growth']['rs_matic_growth_pct']:.4f}%; lp rg: {t['lp_growth']['rg_matic_growth_pct']:.4f}%",
            f"- cfg: buyback={c['buyback_pol']}, rebalance={c['rebalance_pol']}, arb_probe={c['arb_probe_pol']}, bot_sell={c['bot_sell_amount']}, bot_thr={c['bot_sell_threshold']}, lp_re={c['lp_reinvest_owner_matic']}",
            "",
        ])

    if feasible:
        lines.append("## Top feasible")
        lines.append("")
        for i, t in enumerate(feasible[:5], 1):
            c = t["config"]
            lines.extend([
                f"### F{i}",
                f"- pnl: {t['pnl_matic']:.6f} MATIC; roi: {t['roi_pct']:.4f}%; dd: {t['max_drawdown_pct']:.4f}%",
                f"- lp rs: {t['lp_growth']['rs_matic_growth_pct']:.4f}%; lp rg: {t['lp_growth']['rg_matic_growth_pct']:.4f}%",
                f"- cfg: buyback={c['buyback_pol']}, rebalance={c['rebalance_pol']}, arb_probe={c['arb_probe_pol']}, bot_sell={c['bot_sell_amount']}, bot_thr={c['bot_sell_threshold']}, lp_re={c['lp_reinvest_owner_matic']}",
                "",
            ])

    Path("robot_param_search_summary.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"total runs={len(all_runs)} feasible={len(feasible)}")
    best = all_runs[0]
    print(f"best_any pnl={best['pnl_matic']:.6f} roi={best['roi_pct']:.4f}% lp_rs={best['lp_growth']['rs_matic_growth_pct']:.4f}% lp_rg={best['lp_growth']['rg_matic_growth_pct']:.4f}% dd={best['max_drawdown_pct']:.4f}%")


if __name__ == "__main__":
    main()
