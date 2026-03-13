#!/usr/bin/env python3
"""Deterministic 150-cycle run of full CAShero mechanics model.

Loads the full simulator from `SINERGY SYSTEM FINANSE ECOSYSTEM.py` and runs 150 cycles
with fixed RNG seed for reproducibility ("exact" replay).
"""

import importlib.util
import json
import random
import sys
import types
from pathlib import Path

# Optional dependency shim: the model imports tabulate for pretty-print only.
if "tabulate" not in sys.modules:
    tabulate_mod = types.ModuleType("tabulate")
    def _tabulate(rows, headers=None, tablefmt=None):
        return "tabulate_unavailable"
    tabulate_mod.tabulate = _tabulate
    sys.modules["tabulate"] = tabulate_mod

MODULE_PATH = Path("SINERGY SYSTEM FINANSE ECOSYSTEM.py")


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("cashero_full_model", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    random.seed(42)

    m = load_module(MODULE_PATH)
    sim = m.CasheroSimulator(m.ModelConfig(), m.ZeroDay())
    history = sim.run(days=150, verbose=False)

    start = history[0]    # day 0
    end = history[-1]     # day 150

    pnl_nav = end.N - start.N
    pnl_assets = end.A - start.A
    pnl_reserve = end.B - start.B
    roi_nav_pct = (pnl_nav / start.N * 100) if start.N else 0.0

    report = {
        "cycles": 150,
        "seed": 42,
        "start_day": start.day,
        "end_day": end.day,
        "start": {
            "P_spot": start.P_spot,
            "P_safe": start.P_safe,
            "B": start.B,
            "A": start.A,
            "N": start.N,
            "K": start.K,
            "STS": start.STS,
            "D": start.D,
            "C": start.C,
        },
        "end": {
            "P_spot": end.P_spot,
            "P_safe": end.P_safe,
            "B": end.B,
            "A": end.A,
            "N": end.N,
            "K": end.K,
            "STS": end.STS,
            "D": end.D,
            "C": end.C,
            "emission_paused": end.emission_paused,
            "emergency_mode": end.emergency_mode,
            "total_locked": end.total_locked,
            "lock_count": end.lock_count,
            "avg_lock_apr": end.avg_lock_apr,
            "projects_funded_total": sum(p.funding_received for p in end.projects.values()),
            "holder_rewards_total": sum(s.holder_rewards_today for s in history),
        },
        "profit_loss": {
            "nav_pnl_matic": pnl_nav,
            "assets_pnl_matic": pnl_assets,
            "reserve_pnl_matic": pnl_reserve,
            "nav_roi_pct": roi_nav_pct,
        },
    }

    Path("exact_150_cycles_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Exact simulation report (150 cycles)",
        "",
        f"- Cycles: {report['cycles']}",
        f"- Random seed: {report['seed']}",
        "",
        "## Start (day 0)",
        f"- P_spot: {start.P_spot:.6f}",
        f"- P_safe: {start.P_safe:.6f}",
        f"- B: {start.B:.6f}",
        f"- A: {start.A:.6f}",
        f"- N (NAV): {start.N:.6f}",
        f"- K: {start.K:.6f}",
        f"- STS: {start.STS:.6f}",
        "",
        "## End (day 150)",
        f"- P_spot: {end.P_spot:.6f}",
        f"- P_safe: {end.P_safe:.6f}",
        f"- B: {end.B:.6f}",
        f"- A: {end.A:.6f}",
        f"- N (NAV): {end.N:.6f}",
        f"- K: {end.K:.6f}",
        f"- STS: {end.STS:.6f}",
        f"- D: {end.D:.6f}",
        f"- C: {end.C:.6f}",
        f"- Emission paused: {end.emission_paused}",
        f"- Emergency mode: {end.emergency_mode}",
        "",
        "## Profit / Loss",
        f"- NAV PnL: {pnl_nav:.6f} MATIC",
        f"- Assets PnL: {pnl_assets:.6f} MATIC",
        f"- Reserve (B) PnL: {pnl_reserve:.6f} MATIC",
        f"- NAV ROI: {roi_nav_pct:.4f}%",
        "",
        "## Mechanic aggregates",
        f"- Projects funded total: {sum(p.funding_received for p in end.projects.values()):.6f}",
        f"- Holder rewards total: {sum(s.holder_rewards_today for s in history):.6f}",
        f"- Active lock count: {end.lock_count}",
        f"- Total locked CASRS: {end.total_locked:.6f}",
        f"- Average lock APR: {end.avg_lock_apr * 100:.4f}%",
    ]

    Path("exact_150_cycles_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("Saved exact_150_cycles_report.json and exact_150_cycles_report.md")
    print(f"NAV PnL: {pnl_nav:.6f} MATIC ({roi_nav_pct:.4f}%)")


if __name__ == "__main__":
    main()
