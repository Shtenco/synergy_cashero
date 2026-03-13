"""
Run N cycles of the Sinergia bot v2 with interval (defaults: 20 cycles, 20s).
Writes a markdown report to report_cycle_1.md and appends to bot_v2.log.
Designed to survive RPC hiccups: errors per step are logged and cycle continues.
"""
import os
import time
import json
from datetime import datetime, timezone

from sinergia_bot import strategy_step, balances, get_metrics, accounts, LOG_PATH

ROOT = os.path.dirname(__file__)
REPORT_PATH = os.path.join(ROOT, "report_cycle_1.md")


def snapshot(label: str):
    return {
        "label": label,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metrics": get_metrics(),
        "owner": balances(accounts[0].address),
        "bot1": balances(accounts[1].address),
        "bot2": balances(accounts[2].address),
    }


def main():
    cycles = int(os.getenv("CYCLES", "20"))
    interval = int(os.getenv("CYCLE_SEC", "20"))
    snapshots = []
    for i in range(cycles):
        snapshots.append(snapshot(f"cycle_{i}_before"))
        try:
            strategy_step()
        except Exception as e:
            snapshots.append({"label": f"cycle_{i}_error", "error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()})
        else:
            snapshots.append(snapshot(f"cycle_{i}_after"))
        if i != cycles - 1:
            time.sleep(interval)

    # write report
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("# Отчет: первый прогон бота v2 (10 циклов по 60 секунд)\n")
        f.write(f"- Старт: {snapshots[0]['timestamp']}\n")
        f.write(f"- Финиш: {snapshots[-1]['timestamp']}\n")
        f.write(f"- Логи: {LOG_PATH}\n\n")
        def fmt_bal(b):
            return f"MATIC: {float(b['matic']):.6f}, CASRS: {b['casrs']:.2f}, CASRG: {b['casrg']:.2f}"
        for s in snapshots:
            f.write(f"## {s['label']}\n")
            if "metrics" in s:
                m = s["metrics"]
                f.write(f"- metrics: P_spot {m['P_spot']:.6f}, P_twap {m['P_twap']:.6f}, P_safe {m['P_safe']:.6f}, A {m['A']:.2f}, K {m['K']:.4f}, STS {m['STS']:.4f}, emergency {m['emergency']}, paused {m['paused']}\n")
                f.write(f"- owner: {fmt_bal(s['owner'])}\n")
                f.write(f"- bot1: {fmt_bal(s['bot1'])}\n")
                f.write(f"- bot2: {fmt_bal(s['bot2'])}\n\n")
            else:
                f.write(f"- error: {s['error']}\n\n")
    print("Report saved to", REPORT_PATH)


if __name__ == "__main__":
    main()
