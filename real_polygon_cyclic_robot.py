#!/usr/bin/env python3
"""Real multi-RPC cyclic robot for Polygon.

What it does (live mode):
1) Sequential buys from 3 wallets (owner -> bot1 -> bot2).
2) Sequential partial profit taking when wallet position is in profit.
3) Mandatory LP reinvestment by owner into CASRS/WMATIC via addLiquidityETH.
4) RPC rotation + randomized delays to reduce repetitive access patterns.

Use with caution: this script signs and sends real transactions.
"""

import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from web3 import Web3

try:
    from web3.middleware import geth_poa_middleware
except ImportError:
    from web3.middleware.proof_of_authority import ExtraDataToPOAMiddleware as geth_poa_middleware

CHAIN_ID = 137
ROUTER = Web3.to_checksum_address("0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff")
WETH = Web3.to_checksum_address("0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270")

def _load_default_token(name: str) -> str:
    import json
    with open("mainnet-addresses.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["v2"][name]


CASRS = Web3.to_checksum_address(os.getenv("CASRS_ADDRESS", _load_default_token("casrs")))
CASRG = Web3.to_checksum_address(os.getenv("CASRG_ADDRESS", _load_default_token("casrg")))

LOG_PATH = os.getenv("REAL_BOT_LOG", "real_polygon_cyclic_robot.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger("real_polygon_cyclic_robot")


def read_env_file(path: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def load_private_key(path: str) -> str:
    """Support both formats used in repo:
    1) KEY=... (e.g. owner.env)
    2) raw private key in a single line (e.g. bot1.env/bot2.env)
    """
    env = read_env_file(path)
    for k in ("PRIVATE_KEY", "OWNER_PRIVATE_KEY", "BOT_PRIVATE_KEY"):
        if env.get(k):
            return env[k]

    if not os.path.exists(path):
        raise RuntimeError(f"Missing key file: {path}")

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip().strip('"').strip("'")
            if not raw or raw.startswith("#"):
                continue
            if "=" in raw:
                # unknown key name line, skip; known names handled via read_env_file
                continue
            return raw

    raise RuntimeError(f"No private key found in {path}")


ERC20_ABI = [
    {"name": "balanceOf", "inputs": [{"name": "account", "type": "address"}], "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"name": "approve", "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
]

ROUTER_ABI = [
    {
        "name": "swapExactETHForTokensSupportingFeeOnTransferTokens",
        "inputs": [
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "name": "swapExactTokensForETHSupportingFeeOnTransferTokens",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "name": "addLiquidityETH",
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "amountTokenDesired", "type": "uint256"},
            {"name": "amountTokenMin", "type": "uint256"},
            {"name": "amountETHMin", "type": "uint256"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [
            {"name": "amountToken", "type": "uint256"},
            {"name": "amountETH", "type": "uint256"},
            {"name": "liquidity", "type": "uint256"},
        ],
        "stateMutability": "payable",
        "type": "function",
    },
]


@dataclass
class Account:
    name: str
    private_key: str
    address: str
    cost_basis: float = 0.0


class RpcPool:
    def __init__(self, endpoints: List[str]):
        self.web3_list: List[Web3] = []
        for rpc in endpoints:
            rpc = rpc.strip()
            if not rpc:
                continue
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            self.web3_list.append(w3)
        if not self.web3_list:
            raise RuntimeError("No RPC endpoints configured")
        self.idx = 0

    def next(self) -> Web3:
        w3 = self.web3_list[self.idx % len(self.web3_list)]
        self.idx += 1
        return w3

    def connected(self) -> int:
        ok = 0
        for w3 in self.web3_list:
            try:
                if w3.is_connected():
                    ok += 1
            except Exception:
                pass
        return ok


class RealCyclicRobot:
    def __init__(self):
        rpcs = os.getenv(
            "RPC_POLYGON_LIST",
            "https://polygon-rpc.com,https://polygon-bor-rpc.publicnode.com,https://rpc.ankr.com/polygon",
        ).split(",")
        self.pool = RpcPool(rpcs)
        self.router = self.pool.next().eth.contract(address=ROUTER, abi=ROUTER_ABI)
        self.casrs = self.pool.next().eth.contract(address=CASRS, abi=ERC20_ABI)
        self.casrg = self.pool.next().eth.contract(address=CASRG, abi=ERC20_ABI)

        self.buy_matic = 1.0  # fixed buy size per wallet per cycle (1 POL)
        self.take_profit = float(os.getenv("REAL_TAKE_PROFIT", "0.20"))
        self.lp_invest_matic = float(os.getenv("REAL_LP_INVEST_MATIC", "0.05"))
        self.min_delay = float(os.getenv("MIN_WALLET_DELAY_SEC", "2.0"))
        self.max_delay = float(os.getenv("MAX_WALLET_DELAY_SEC", "8.0"))
        self.cycle_sleep = int(os.getenv("CYCLE_SEC", "45"))

        self.accounts = self._load_accounts()
        if len(self.accounts) != 3:
            raise RuntimeError("Need exactly 3 wallets: owner.env, bot1.env, bot2.env")

    def _load_accounts(self) -> List[Account]:
        out = []
        for name, path in [("owner", "owner.env"), ("bot1", "bot1.env"), ("bot2", "bot2.env")]:
            key = load_private_key(path)
            w3 = self.pool.next()
            acc = w3.eth.account.from_key(key)
            out.append(Account(name=name, private_key=key, address=acc.address))
        return out

    def _gas(self, w3: Web3) -> Dict[str, int]:
        gp = w3.eth.gas_price
        tip = max(w3.to_wei(30, "gwei"), int(gp * 0.4))
        max_fee = max(w3.to_wei(90, "gwei"), int(gp * 2))
        return {"maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip}

    def _send(self, account: Account, tx: Dict[str, Any], retries: int = 3) -> str:
        last_err = None
        for _ in range(retries):
            w3 = self.pool.next()
            try:
                nonce = w3.eth.get_transaction_count(account.address, "pending")
                tx_local = dict(tx)
                tx_local["nonce"] = nonce
                tx_local["chainId"] = CHAIN_ID
                tx_local.update(self._gas(w3))
                if "from" not in tx_local:
                    tx_local["from"] = account.address
                signed = w3.eth.account.sign_transaction(tx_local, account.private_key)
                raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction")
                txh = w3.eth.send_raw_transaction(raw)
                rcpt = w3.eth.wait_for_transaction_receipt(txh, timeout=240)
                if rcpt.status != 1:
                    raise RuntimeError(f"status=0 hash={txh.hex()}")
                return txh.hex()
            except Exception as e:
                last_err = e
                time.sleep(random.uniform(0.7, 2.5))
        raise RuntimeError(f"Send failed for {account.name}: {last_err}")

    def _balance_token(self, token_contract, addr: str) -> int:
        return token_contract.functions.balanceOf(addr).call()

    def _delay(self):
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def buy_token(self, account: Account, token: str, amount_matic: float) -> str:
        deadline = int(time.time()) + 600
        fn = self.router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            0, [WETH, token], account.address, deadline
        )
        tx = fn.build_transaction(
            {"from": account.address, "value": Web3.to_wei(amount_matic, "ether")}
        )
        return self._send(account, tx)

    def sell_token(self, account: Account, token_contract, token_addr: str, amount_tokens_wei: int) -> str:
        approve = token_contract.functions.approve(ROUTER, amount_tokens_wei).build_transaction(
            {"from": account.address}
        )
        self._send(account, approve)

        fn = self.router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
            amount_tokens_wei, 0, [token_addr, WETH], account.address, int(time.time()) + 600
        )
        tx = fn.build_transaction({"from": account.address})
        return self._send(account, tx)

    def add_lp_from_owner(self, token_contract, token_addr: str, owner: Account, total_matic: float) -> None:
        half = total_matic / 2
        before = self._balance_token(token_contract, owner.address)
        self.buy_token(owner, token_addr, half)
        after = self._balance_token(token_contract, owner.address)
        token_got = max(0, after - before)
        if token_got == 0:
            log.warning("No token acquired for LP add; skip")
            return

        approve = token_contract.functions.approve(ROUTER, token_got).build_transaction({"from": owner.address})
        self._send(owner, approve)

        token_min = 0
        eth_min = 0
        fn = self.router.functions.addLiquidityETH(
            token_addr,
            token_got,
            token_min,
            eth_min,
            owner.address,
            int(time.time()) + 600,
        )
        tx = fn.build_transaction({"from": owner.address, "value": Web3.to_wei(half, "ether")})
        self._send(owner, tx)

    def cycle(self):
        owner, bot1, bot2 = self.accounts

        log.info("Cycle start: sequential buys")
        for acc in [owner, bot1, bot2]:
            try:
                txh = self.buy_token(acc, CASRS, self.buy_matic)
                log.info("%s buy CASRS tx=%s", acc.name, txh)
            except Exception as e:
                log.error("%s buy failed: %s", acc.name, e)
            self._delay()

        log.info("Cycle: sequential partial profit taking")
        for acc in [owner, bot1, bot2]:
            try:
                bal = self._balance_token(self.casrs, acc.address)
                if bal > 0:
                    sell_amt = int(bal * self.take_profit)
                    if sell_amt > 0:
                        txh = self.sell_token(acc, self.casrs, CASRS, sell_amt)
                        log.info("%s partial sell CASRS tx=%s", acc.name, txh)
            except Exception as e:
                log.error("%s partial sell failed: %s", acc.name, e)
            self._delay()

        log.info("Cycle: mandatory dual-token LP reinvest (CASRS/WMATIC)")
        try:
            self.add_lp_from_owner(self.casrs, CASRS, owner, self.lp_invest_matic)
        except Exception as e:
            log.error("LP add failed: %s", e)

        log.info("Cycle complete")

    def run(self):
        ok = self.pool.connected()
        log.info("RPC online: %s/%s", ok, len(self.pool.web3_list))
        log.info("Wallets: %s", ", ".join(a.address for a in self.accounts))
        log.info("Fixed buy size per wallet: %.3f POL", self.buy_matic)
        while True:
            self.cycle()
            time.sleep(self.cycle_sleep)


if __name__ == "__main__":
    bot = RealCyclicRobot()
    bot.run()
