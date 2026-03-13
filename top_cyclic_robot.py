#!/usr/bin/env python3
"""
TOP cyclic robot for the Sinergia dual-loop model.

Model goals:
1) Sequential buy with 3 wallets.
2) Sequential partial profit-taking with 3 wallets.
3) Mandatory reinvestment into liquidity pool (both tokens).
4) Adaptive emission + burn policy with growth bias.
5) Growth target for LP depth and protocol reserves (under positive flow regime).

This is a deterministic simulation model (research/backtesting), not trading advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class Wallet:
    name: str
    base: float
    token: float = 0.0
    cost_basis: float = 0.0  # weighted avg entry in base per token

    def buy(self, token_out: float, base_in: float) -> None:
        total_cost = self.cost_basis * self.token + base_in
        self.token += token_out
        self.cost_basis = total_cost / self.token if self.token > 0 else 0.0
        self.base -= base_in

    def sell(self, token_in: float, base_out: float) -> float:
        token_in = min(token_in, self.token)
        pnl = base_out - token_in * self.cost_basis
        self.token -= token_in
        self.base += base_out
        if self.token <= 1e-12:
            self.token = 0.0
            self.cost_basis = 0.0
        return max(0.0, pnl)


@dataclass
class Pool:
    x_token: float
    y_base: float
    fee: float = 0.003

    @property
    def price(self) -> float:
        return self.y_base / self.x_token

    @property
    def k(self) -> float:
        return self.x_token * self.y_base

    def buy_token(self, base_in: float) -> float:
        effective_in = base_in * (1.0 - self.fee)
        x_new = self.k / (self.y_base + effective_in)
        token_out = self.x_token - x_new
        self.x_token = x_new
        self.y_base += effective_in
        return token_out

    def sell_token(self, token_in: float) -> float:
        effective_in = token_in * (1.0 - self.fee)
        y_new = self.k / (self.x_token + effective_in)
        base_out = self.y_base - y_new
        self.x_token += effective_in
        self.y_base = y_new
        return base_out

    def add_liquidity(self, base_add: float, token_add: float) -> None:
        self.y_base += base_add
        self.x_token += token_add


@dataclass
class Treasury:
    reserve_base: float
    reserve_token: float
    liq_fund_base: float


@dataclass
class Config:
    take_profit: float = 0.25            # share of position to realize when profitable
    fee_to_liq_fund: float = 0.50        # from protocol fees
    pnl_to_liq_fund: float = 0.35        # from realized pnl
    pnl_to_reserve: float = 0.45         # from realized pnl
    pnl_to_burn: float = 0.20            # from realized pnl
    liq_deploy_share: float = 0.20       # share of liq fund deployed each cycle
    reserve_sale_share: float = 0.0002   # daily fraction of reserve token sold to feed liq fund
    emission_rate: float = 0.0035        # base emission rate
    burn_rate: float = 0.0010            # base burn rate
    target_growth: float = 0.002         # target cycle growth in LP depth


@dataclass
class StepStat:
    cycle: int
    price: float
    lp_depth: float
    reserve_nav: float
    protocol_nav: float


class TopCyclicRobotModel:
    def __init__(self, pool: Pool, wallets: List[Wallet], treasury: Treasury, cfg: Config):
        self.pool = pool
        self.wallets = wallets
        self.treasury = treasury
        self.cfg = cfg
        self.history: List[StepStat] = []

    def _wallet_buy_notional(self, w: Wallet, idx: int) -> float:
        frac = (0.03, 0.02, 0.015)[idx]
        return max(0.0, min(w.base * frac, w.base - 1e-9))

    def _adaptive_emission_burn(self, lp_growth: float) -> None:
        p = self.pool.price
        emission = self.cfg.emission_rate * self.pool.x_token * max(0.0, self.cfg.target_growth - lp_growth + 0.001)
        burn = self.cfg.burn_rate * self.pool.x_token * max(0.0, lp_growth - self.cfg.target_growth)

        self.treasury.reserve_token += emission
        burn_from_reserve = min(self.treasury.reserve_token, burn)
        self.treasury.reserve_token -= burn_from_reserve

        # extra anti-inflation burn funded by pnl bucket (via market buyback)
        burn_base_budget = min(self.treasury.reserve_base * 0.001, self.treasury.reserve_base)
        if burn_base_budget > 0:
            token_bought = self.pool.buy_token(burn_base_budget)
            self.treasury.reserve_base -= burn_base_budget
            # bought tokens are burned => they do not enter balances
            _ = token_bought

        # maintain reserve quality: keep a part of reserve in base
        if self.treasury.reserve_token > 0 and self.treasury.reserve_base < 0.1 * p * self.treasury.reserve_token:
            to_sell = 0.01 * self.treasury.reserve_token
            out = self.pool.sell_token(to_sell)
            self.treasury.reserve_token -= to_sell
            self.treasury.reserve_base += out

    def step(self, cycle: int) -> None:
        prev_lp_depth = self.pool.y_base * 2.0

        # 1) sequential buy from three wallets
        fee_income = 0.0
        for i, w in enumerate(self.wallets):
            base_in = self._wallet_buy_notional(w, i)
            if base_in <= 0:
                continue
            token_out = self.pool.buy_token(base_in)
            w.buy(token_out, base_in)
            fee_income += base_in * self.pool.fee

        # 2) sequential partial profit-taking from three wallets
        realized_pnl = 0.0
        for w in self.wallets:
            if w.token <= 0:
                continue
            if self.pool.price <= w.cost_basis:
                continue
            token_in = w.token * self.cfg.take_profit
            base_out = self.pool.sell_token(token_in)
            realized_pnl += w.sell(token_in, base_out)

        # 3) fund LP growth from fees + realized profits + controlled reserve sales
        self.treasury.liq_fund_base += fee_income * self.cfg.fee_to_liq_fund
        self.treasury.reserve_base += fee_income * (1.0 - self.cfg.fee_to_liq_fund)

        self.treasury.liq_fund_base += realized_pnl * self.cfg.pnl_to_liq_fund
        self.treasury.reserve_base += realized_pnl * self.cfg.pnl_to_reserve

        burn_budget = realized_pnl * self.cfg.pnl_to_burn
        if burn_budget > 0:
            token_bought = self.pool.buy_token(burn_budget)
            _ = token_bought

        reserve_sale = self.treasury.reserve_token * self.cfg.reserve_sale_share
        if reserve_sale > 0:
            base_from_sale = self.pool.sell_token(reserve_sale)
            self.treasury.reserve_token -= reserve_sale
            self.treasury.liq_fund_base += base_from_sale

        # 4) mandatory LP injection with both assets (proportional add keeps price stable)
        deploy_base = self.treasury.liq_fund_base * self.cfg.liq_deploy_share
        deploy_token = deploy_base / self.pool.price if self.pool.price > 0 else 0.0
        deploy_token = min(deploy_token, self.treasury.reserve_token)
        deploy_base = deploy_token * self.pool.price

        self.pool.add_liquidity(deploy_base, deploy_token)
        self.treasury.liq_fund_base -= deploy_base
        self.treasury.reserve_token -= deploy_token

        # 5) adaptive emission + burn control
        new_lp_depth = self.pool.y_base * 2.0
        lp_growth = (new_lp_depth - prev_lp_depth) / max(1e-12, prev_lp_depth)
        self._adaptive_emission_burn(lp_growth)

        reserve_nav = self.treasury.reserve_base + self.treasury.reserve_token * self.pool.price
        wallet_nav = sum(w.base + w.token * self.pool.price for w in self.wallets)

        self.history.append(
            StepStat(
                cycle=cycle,
                price=self.pool.price,
                lp_depth=new_lp_depth,
                reserve_nav=reserve_nav,
                protocol_nav=wallet_nav + reserve_nav,
            )
        )

    def run(self, cycles: int = 120) -> List[StepStat]:
        for c in range(1, cycles + 1):
            self.step(c)
        return self.history


def main() -> None:
    pool = Pool(x_token=1_000_000.0, y_base=100_000.0)
    wallets = [
        Wallet("owner", base=30_000.0),
        Wallet("bot_1", base=10_000.0),
        Wallet("bot_2", base=10_000.0),
    ]
    treasury = Treasury(reserve_base=20_000.0, reserve_token=250_000.0, liq_fund_base=0.0)
    cfg = Config()

    model = TopCyclicRobotModel(pool, wallets, treasury, cfg)
    hist = model.run(cycles=180)

    first, last = hist[0], hist[-1]
    print("=== TOP Cyclic Robot Simulation ===")
    print(f"cycles: {len(hist)}")
    print(f"price: {first.price:.6f} -> {last.price:.6f}")
    print(f"LP depth (2Y): {first.lp_depth:.2f} -> {last.lp_depth:.2f}")
    print(f"reserve NAV: {first.reserve_nav:.2f} -> {last.reserve_nav:.2f}")
    print(f"protocol NAV: {first.protocol_nav:.2f} -> {last.protocol_nav:.2f}")


if __name__ == "__main__":
    main()
