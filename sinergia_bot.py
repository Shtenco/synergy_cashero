import json
import os
import time
import logging
from dataclasses import dataclass
from typing import Dict, Any

from dotenv import dotenv_values
from web3 import Web3
try:
    from web3.middleware import geth_poa_middleware
except ImportError:
    from web3.middleware.proof_of_authority import ExtraDataToPOAMiddleware as geth_poa_middleware

ROOT = os.path.dirname(__file__)
ADDR = json.load(open(os.path.join(ROOT, "mainnet-addresses.json")))
CASRS_ADDR = ADDR["v2"]["casrs"]
CASRG_ADDR = ADDR["v2"]["casrg"]
FACTORY = Web3.to_checksum_address("0x5757371414417b8c6caad45baef941abc7d3ab32")  # QuickSwap V2

RPC = os.getenv("RPC_POLYGON", "https://polygon-bor-rpc.publicnode.com")
w3 = Web3(Web3.HTTPProvider(RPC))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)

LOG_PATH = os.path.join(ROOT, "bot_v2.log")

# Tunable parameters (pulled from env with defaults)
CONFIG = {
    "cycle_sec": int(os.getenv("CYCLE_SEC", "60")),
    "trade_cap_pol": float(os.getenv("TRADE_CAP_POL", "5")),
    "buyback_pol": float(os.getenv("BUYBACK_POL", "1")),
    "rebalance_pol": float(os.getenv("REBALANCE_POL", "1")),
    "repay_fraction": float(os.getenv("REPAY_FRACTION", "0.5")),
    "rebalance_thresh": float(os.getenv("REBALANCE_THRESH", "0.02")),  # 2% from TWAP
    # model thresholds
    "k_buyback": float(os.getenv("K_BUYBACK", "1.3")),
    "sts_buyback": float(os.getenv("STS_BUYBACK", "1.1")),
    "k_repay": float(os.getenv("K_REPAY", "1.15")),
    # slippage for arb sanity (not enforced on chain here, but for checks)
    "arb_slippage": float(os.getenv("ARB_SLIPPAGE", "0.01")),
    # amount for tri-arb probe
    "arb_probe_pol": float(os.getenv("ARB_PROBE_POL", "0.5")),
}
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger("sinergia_bot_v2")


def load_wallet(name: str):
    env = dotenv_values(os.path.join(ROOT, "wallets", f"{name}.env"))
    return env["PRIVATE_KEY"], env["ADDRESS"]


OWNER_PK, OWNER_ADDR = load_wallet("owner")
BOT1_PK, BOT1_ADDR = load_wallet("bot1")
BOT2_PK, BOT2_ADDR = load_wallet("bot2")


ERC20_ABI = [
    {"name": "balanceOf", "inputs": [{"name": "account", "type": "address"}], "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"name": "approve", "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"name": "transfer", "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"name": "totalSupply", "inputs": [], "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

CASRS_ABI = ERC20_ABI + [
    {"name": "getMetrics", "inputs": [], "outputs": [
        {"components": [
            {"name": "P_spot", "type": "uint256"},
            {"name": "P_twap", "type": "uint256"},
            {"name": "P_safe", "type": "uint256"},
            {"name": "A", "type": "uint256"},
            {"name": "K", "type": "uint256"},
            {"name": "STS", "type": "uint256"},
            {"name": "emergency", "type": "bool"},
            {"name": "emissionPaused", "type": "bool"},
        ], "type": "tuple"}], "stateMutability": "view", "type": "function"},
    {"name": "params", "inputs": [], "outputs": [
        {"name": "hRS", "type": "uint256"},
        {"name": "hRG", "type": "uint256"},
        {"name": "rho", "type": "uint256"},
        {"name": "omega", "type": "uint256"},
        {"name": "minCoverage", "type": "uint256"},
        {"name": "fee", "type": "uint256"},
    ], "stateMutability": "view", "type": "function"},
    {"name": "updateReserves", "inputs": [
        {"name": "X", "type": "uint256"},
        {"name": "Y", "type": "uint256"},
        {"name": "F", "type": "uint256"}
    ], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "updateSystemState", "inputs": [
        {"name": "B", "type": "uint256"},
        {"name": "C", "type": "uint256"},
        {"name": "R_RS", "type": "uint256"},
        {"name": "R_RG", "type": "uint256"},
        {"name": "D", "type": "uint256"},
        {"name": "S", "type": "uint256"}
    ], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
]

CASRG_EXTRA_ABI = [
    {"name": "mintAgainstCollateral", "inputs": [{"name": "rsAmount", "type": "uint256"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "repay", "inputs": [{"name": "rgAmount", "type": "uint256"}], "outputs": [], "stateMutability": "nonpayable", "type": "function"},
]

ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff"  # QuickSwap V2
WETH = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
ROUTER_ABI = [
    {"name": "swapExactETHForTokensSupportingFeeOnTransferTokens",
     "inputs": [
         {"name": "amountOutMin", "type": "uint256"},
         {"name": "path", "type": "address[]"},
         {"name": "to", "type": "address"},
         {"name": "deadline", "type": "uint256"}
     ],
     "outputs": [], "stateMutability": "payable", "type": "function"},
    {"name": "swapExactTokensForETHSupportingFeeOnTransferTokens",
     "inputs": [
         {"name": "amountIn", "type": "uint256"},
         {"name": "amountOutMin", "type": "uint256"},
         {"name": "path", "type": "address[]"},
         {"name": "to", "type": "address"},
         {"name": "deadline", "type": "uint256"}
     ],
     "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "getAmountsOut",
     "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "path", "type": "address[]"}],
     "outputs": [{"name": "amounts", "type": "uint256[]"}],
     "stateMutability": "view", "type": "function"},
]

casrs = w3.eth.contract(address=CASRS_ADDR, abi=CASRS_ABI)
casrg = w3.eth.contract(address=CASRG_ADDR, abi=ERC20_ABI + CASRG_EXTRA_ABI)
router = w3.eth.contract(address=ROUTER, abi=ROUTER_ABI)
factory = w3.eth.contract(address=FACTORY, abi=[
    {"name": "getPair", "inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"}], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"}
])
PAIR_ABI = [
    {"name": "getReserves", "inputs": [], "outputs": [
        {"name": "_reserve0", "type": "uint112"},
        {"name": "_reserve1", "type": "uint112"},
        {"name": "_blockTimestampLast", "type": "uint32"}
    ], "stateMutability": "view", "type": "function"},
    {"name": "token0", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"name": "token1", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"}
]


@dataclass
class Account:
    name: str
    address: str
    key: str


accounts = [
    Account("owner", OWNER_ADDR, OWNER_PK),
    Account("bot1", BOT1_ADDR, BOT1_PK),
    Account("bot2", BOT2_ADDR, BOT2_PK),
]


def gas_opts():
    gp = w3.eth.gas_price
    min_tip = w3.to_wei(25, "gwei")
    tip = max(int(gp * 0.5), min_tip)
    max_fee = max(int(gp * 2), w3.to_wei(100, "gwei"))
    return {"maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip}


def sign_send(account: Account, tx: Dict[str, Any]) -> str:
    signed = w3.eth.account.sign_transaction(tx, private_key=account.key)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction")
    txh = w3.eth.send_raw_transaction(raw)
    rcpt = w3.eth.wait_for_transaction_receipt(txh)
    log.info(f"{account.name} tx {txh.hex()} status={rcpt.status}")
    return txh.hex()


def balances(addr: str) -> Dict[str, float]:
    matic = w3.from_wei(w3.eth.get_balance(addr), "ether")
    rs = casrs.functions.balanceOf(addr).call() / 1e18
    rg = casrg.functions.balanceOf(addr).call() / 1e18
    return {"matic": float(matic), "casrs": rs, "casrg": rg}


def get_pair_reserves(token_addr: str):
    pair = factory.functions.getPair(token_addr, WETH).call()
    if pair == "0x0000000000000000000000000000000000000000":
        return None
    p = w3.eth.contract(address=pair, abi=PAIR_ABI)
    r0, r1, _ = p.functions.getReserves().call()
    t0 = p.functions.token0().call()
    if t0.lower() == token_addr.lower():
        reserve_token, reserve_wmatic = r0, r1
    else:
        reserve_token, reserve_wmatic = r1, r0
    return reserve_token, reserve_wmatic


def update_onchain_state():
    """Push real reserves and debt into CASRSv2 to make metrics meaningful."""
    owner = accounts[0]
    rs_res = get_pair_reserves(CASRS_ADDR)
    rg_res = get_pair_reserves(CASRG_ADDR)
    if not rs_res or not rg_res:
        log.warning("pair reserves not found; skip update_onchain_state")
        return
    # Use CASRS/WMATIC pool as X/Y
    X = rs_res[0]  # CASRS
    Y = rs_res[1]  # WMATIC
    F = casrs.functions.totalSupply().call()  # approximate free float
    D = casrg.functions.totalSupply().call()
    S = casrs.functions.totalSupply().call()
    # rough B,C,R_RS,R_RG from reserves
    B = Y  # treat WMATIC reserve as base asset in wei
    C = X  # collateral CASRS
    R_RS = X // 2
    R_RG = rg_res[0]

    tx1 = casrs.functions.updateReserves(X, Y, F).build_transaction({
        "from": owner.address,
        "nonce": w3.eth.get_transaction_count(owner.address),
        "chainId": 137,
        **gas_opts(),
    })
    sign_send(owner, tx1)

    tx2 = casrs.functions.updateSystemState(B, C, R_RS, R_RG, D, S).build_transaction({
        "from": owner.address,
        "nonce": w3.eth.get_transaction_count(owner.address),
        "chainId": 137,
        **gas_opts(),
    })
    sign_send(owner, tx2)


def get_metrics():
    m = casrs.functions.getMetrics().call()
    return {
        "P_spot": m[0] / 1e18,
        "P_twap": m[1] / 1e18,
        "P_safe": m[2] / 1e18,
        "A": m[3] / 1e18,
        "K": m[4] / 1e18,
        "STS": m[5] / 1e18,
        "emergency": m[6],
        "paused": m[7],
    }


def buy(account: Account, token_addr: str, amount_matic: float):
    path = [WETH, token_addr]
    func = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
        0, path, account.address, int(time.time()) + 600
    )
    tx = {
        "from": account.address,
        "value": w3.to_wei(amount_matic, "ether"),
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": 137,
        **gas_opts(),
    }
    built = func.build_transaction(tx)
    return sign_send(account, built)


def sell(account: Account, token_addr: str, amount_token: float):
    amt = int(amount_token * 1e18)
    # approve
    approve_tx = casrs.functions.approve(ROUTER, amt).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": 137,
        **gas_opts(),
    }) if token_addr == CASRS_ADDR else casrg.functions.approve(ROUTER, amt).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": 137,
        **gas_opts(),
    })
    sign_send(account, approve_tx)

    path = [token_addr, WETH]
    func = router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
        amt, 0, path, account.address, int(time.time()) + 600
    )
    tx = func.build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": 137,
        **gas_opts(),
    })
    return sign_send(account, tx)


def strategy_step():
    update_onchain_state()
    m = get_metrics()
    log.info(f"metrics {m}")
    # heuristic rules, parameterized
    max_trade = CONFIG["trade_cap_pol"]
    owner = accounts[0]
    b_owner = balances(owner.address)

    # If K > 1.3 and STS > 1.1: buyback CASRS for 1 POL
    if m["K"] > CONFIG["k_buyback"] and m["STS"] > CONFIG["sts_buyback"] and b_owner["matic"] > CONFIG["buyback_pol"]:
        log.info(f"rule: buyback CASRS ({CONFIG['buyback_pol']} POL)")
        buy(owner, CASRS_ADDR, min(CONFIG["buyback_pol"], max_trade))

    # If K < 1.15: repay debt using CASRG of owner if any
    if m["K"] < CONFIG["k_repay"] and b_owner["casrg"] > 10:
        repay_amt = min(b_owner["casrg"] * CONFIG["repay_fraction"], 50)
        log.info(f"rule: repay {repay_amt:.2f} CASRG")
        tx = casrg.functions.repay(int(repay_amt * 1e18)).build_transaction({
            "from": owner.address,
            "nonce": w3.eth.get_transaction_count(owner.address),
            "chainId": 137,
            **gas_opts(),
        })
        sign_send(owner, tx)

    # Simple rebalance to TWAP
    thresh = CONFIG["rebalance_thresh"]
    if b_owner["matic"] > CONFIG["rebalance_pol"]:
        if m["P_spot"] > m["P_twap"] * (1 + thresh):
            log.info(f"rule: rebalance buy CASRG ({CONFIG['rebalance_pol']} POL)")
            buy(owner, CASRG_ADDR, min(CONFIG["rebalance_pol"], max_trade))
        elif m["P_spot"] < m["P_twap"] * (1 - thresh):
            log.info(f"rule: rebalance buy CASRS ({CONFIG['rebalance_pol']} POL)")
            buy(owner, CASRS_ADDR, min(CONFIG["rebalance_pol"], max_trade))

    # Periodic sells for bots if holdings > threshold
    for bot in accounts[1:]:
        b = balances(bot.address)
        if b["casrs"] > 200:
            log.info(f"{bot.name}: sell 100 CASRS")
            sell(bot, CASRS_ADDR, 100)
        if b["casrg"] > 200:
            log.info(f"{bot.name}: sell 100 CASRG")
            sell(bot, CASRG_ADDR, 100)

    # Triangular arbitrage CASRS->WMATIC->CASRG (or reverse) small probe
    try:
        arb_probe = min(CONFIG["arb_probe_pol"], max_trade, b_owner["matic"])
        if arb_probe > 0.1:
            # price RS in MATIC
            out_rs = router.functions.getAmountsOut(
                w3.to_wei(arb_probe, "ether"),
                [WETH, CASRS_ADDR]
            ).call()[-1]
            # price RG in MATIC
            out_rg = router.functions.getAmountsOut(
                w3.to_wei(arb_probe, "ether"),
                [WETH, CASRG_ADDR]
            ).call()[-1]
            # cross quote: RS -> MATIC -> RG
            cross_rg = router.functions.getAmountsOut(
                out_rs,
                [CASRS_ADDR, WETH, CASRG_ADDR]
            ).call()[-1]
            # Expectation: if cross_rg > direct_rg * (1+slip), do arb
            if cross_rg > out_rg * (1 + CONFIG["arb_slippage"]):
                log.info(f"arb: buy CASRS with {arb_probe} POL then swap to CASRG")
                buy(owner, CASRS_ADDR, arb_probe)
                # sell RS for RG
                rs_bal = balances(owner.address)["casrs"]
                sell(owner, CASRS_ADDR, min(rs_bal, 100))  # sell up to 100 RS equivalent
    except Exception as e:
        log.warning(f"arb check failed: {e}")


def main_loop():
    log.info(f"Starting bot v2 loop ({CONFIG['cycle_sec']}s cycle, cap {CONFIG['trade_cap_pol']} POL per step)")
    while True:
        try:
            strategy_step()
        except Exception as e:
            log.error(f"cycle error: {e}")
        time.sleep(CONFIG["cycle_sec"])


if __name__ == "__main__":
    print("RPC:", RPC)
    print("CASRSv2:", CASRS_ADDR)
    print("CASRGv2:", CASRG_ADDR)
    print("Logs:", LOG_PATH)
    main_loop()
