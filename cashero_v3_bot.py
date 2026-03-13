#!/usr/bin/env python3
"""Bot for CASRSv3/CASRGv3 contracts (dual-loop model v3).

Implements:
- 3-wallet sequential buys/sells on CASRS
- periodic state update + growth mint/burn hook
- LP fund loop via CASRSv3.robotSellReserveAndAddLiquidity
- CASRG mint/repay loop hooks
"""

import json
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


def load_key(path: str) -> str:
    if not os.path.exists(path):
        raise RuntimeError(f"missing {path}")
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip().strip('"').strip("'")
            if not s or s.startswith("#"):
                continue
            if "=" in s:
                k, v = s.split("=", 1)
                if k.strip().upper() in {"PRIVATE_KEY", "OWNER_PRIVATE_KEY", "BOT_PRIVATE_KEY"}:
                    return v.strip()
                continue
            return s
    raise RuntimeError(f"no key in {path}")


@dataclass
class Acc:
    name: str
    key: str
    addr: str


RPC = os.getenv("RPC_POLYGON", "https://polygon-rpc.com")
w3 = Web3(Web3.HTTPProvider(RPC))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)

ROUTER = Web3.to_checksum_address("0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff")
WETH = Web3.to_checksum_address("0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270")

CASRS = Web3.to_checksum_address(os.getenv("CASRSV3_ADDRESS", "0x0000000000000000000000000000000000000001"))
CASRG = Web3.to_checksum_address(os.getenv("CASRGV3_ADDRESS", "0x0000000000000000000000000000000000000002"))

ERC20_ABI = [
    {"name": "balanceOf", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"name": "approve", "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}], "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
]

CASRSV3_ABI = ERC20_ABI + [
    {"name": "updateState", "inputs": [
        {"type": "uint256"}, {"type": "uint256"}, {"type": "uint256"}, {"type": "uint256"},
        {"type": "uint256"}, {"type": "uint256"}, {"type": "uint256"}, {"type": "uint256"}, {"type": "uint256"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "mintByGrowth", "inputs": [{"type": "uint256"}], "outputs": [{"type": "uint256"}], "stateMutability": "nonpayable", "type": "function"},
    {"name": "burnByDecline", "inputs": [{"type": "uint256"}, {"type": "uint256"}], "outputs": [{"type": "uint256"}], "stateMutability": "nonpayable", "type": "function"},
    {"name": "robotSellReserveAndAddLiquidity", "inputs": [{"type": "uint256"}, {"type": "uint256"}, {"type": "uint256"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "pTwap", "inputs": [], "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

CASRGV3_ABI = ERC20_ABI + [
    {"name": "mintAgainstCollateral", "inputs": [{"type": "uint256"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "repay", "inputs": [{"type": "uint256"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
]

ROUTER_ABI = [
    {"name": "swapExactETHForTokensSupportingFeeOnTransferTokens", "inputs": [{"type": "uint256"}, {"type": "address[]"}, {"type": "address"}, {"type": "uint256"}], "outputs": [], "stateMutability": "payable", "type": "function"},
    {"name": "swapExactTokensForETHSupportingFeeOnTransferTokens", "inputs": [{"type": "uint256"}, {"type": "uint256"}, {"type": "address[]"}, {"type": "address"}, {"type": "uint256"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
]


def gas_opts() -> Dict[str, int]:
    gp = w3.eth.gas_price
    return {"maxFeePerGas": max(int(gp * 2), w3.to_wei(90, "gwei")), "maxPriorityFeePerGas": max(int(gp * 0.4), w3.to_wei(30, "gwei"))}


def send(acc: Acc, tx: Dict[str, Any]) -> str:
    tx.update({"chainId": 137, "nonce": w3.eth.get_transaction_count(acc.addr), **gas_opts()})
    signed = w3.eth.account.sign_transaction(tx, acc.key)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction")
    h = w3.eth.send_raw_transaction(raw)
    w3.eth.wait_for_transaction_receipt(h)
    return h.hex()


def main():
    if not w3.is_connected():
        raise RuntimeError("rpc not connected")

    owner = w3.eth.account.from_key(load_key("owner.env"))
    bot1 = w3.eth.account.from_key(load_key("bot1.env"))
    bot2 = w3.eth.account.from_key(load_key("bot2.env"))
    accs: List[Acc] = [
        Acc("owner", load_key("owner.env"), owner.address),
        Acc("bot1", load_key("bot1.env"), bot1.address),
        Acc("bot2", load_key("bot2.env"), bot2.address),
    ]

    rs = w3.eth.contract(address=CASRS, abi=CASRSV3_ABI)
    rg = w3.eth.contract(address=CASRG, abi=CASRGV3_ABI)
    router = w3.eth.contract(address=ROUTER, abi=ROUTER_ABI)

    buy_pol = 1.0
    take_profit = 0.2

    while True:
        # sequential buys
        for a in accs:
            fn = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
                0, [WETH, CASRS], a.addr, int(time.time()) + 600
            )
            tx = fn.build_transaction({"from": a.addr, "value": w3.to_wei(buy_pol, "ether")})
            print(a.name, "buy", send(a, tx))
            time.sleep(random.uniform(2, 6))

        # sequential partial sells
        erc = w3.eth.contract(address=CASRS, abi=ERC20_ABI)
        for a in accs:
            bal = erc.functions.balanceOf(a.addr).call()
            amt = int(bal * take_profit)
            if amt > 0:
                ap = erc.functions.approve(ROUTER, amt).build_transaction({"from": a.addr})
                send(a, ap)
                fn = router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
                    amt, 0, [CASRS, WETH], a.addr, int(time.time()) + 600
                )
                tx = fn.build_transaction({"from": a.addr})
                print(a.name, "sell", send(a, tx))
            time.sleep(random.uniform(2, 6))

        # model hooks (owner)
        prev_twap = rs.functions.pTwap().call()
        # NOTE: set real X/Y/F/B/C/R values from oracle/indexer in production
        stx = rs.functions.updateState(1000, 500, 500, 100, 100, 1000, 2000, 200, prev_twap).build_transaction({"from": accs[0].addr})
        send(accs[0], stx)

        mtx = rs.functions.mintByGrowth(prev_twap).build_transaction({"from": accs[0].addr})
        send(accs[0], mtx)

        ltx = rs.functions.robotSellReserveAndAddLiquidity(10, 2000, int(time.time()) + 600).build_transaction({"from": accs[0].addr})
        send(accs[0], ltx)

        # optional debt loop
        try:
            mint_debt = rg.functions.mintAgainstCollateral(w3.to_wei(10, "ether")).build_transaction({"from": accs[1].addr})
            send(accs[1], mint_debt)
        except Exception:
            pass

        time.sleep(45)


if __name__ == "__main__":
    main()
