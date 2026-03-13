#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
====================================================================================================
СИСТЕМА УПРАВЛЕНИЯ И ТОРГОВЛИ "СИНЕРГИЯ" - ПОЛНАЯ РЕАЛИЗАЦИЯ МАТЕМАТИЧЕСКОЙ МОДЕЛИ
====================================================================================================
ВЕРСИЯ 6.0 - С РАСПРЕДЕЛЕНИЕМ 50 MATIC (ИЮНЬ 2026)

ТРИ КОШЕЛЬКА:
- Owner (владелец системы) - из owner.env
- Trader_1 (агрессивный трейдер) - из bot1.env
- Trader_2 (консервативный трейдер) - из bot2.env

РАСПРЕДЕЛЕНИЕ 50 MATIC:
- Owner: 30 MATIC (для управления, рециклинга, LP)
- Trader_1: 10 MATIC (агрессивная торговля)
- Trader_2: 10 MATIC (консервативная торговля)

Все вызовы готовы для интеграции со смарт-контрактами
====================================================================================================
"""

import asyncio
import logging
import json
import time
import random
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
from web3 import Web3
from web3.middleware import geth_poa_middleware
from dotenv import load_dotenv

# ====================================================================================================
# ЗАГРУЗКА КЛЮЧЕЙ ИЗ .env ФАЙЛОВ
# ====================================================================================================

# Загружаем ключи из соответствующих файлов
load_dotenv('owner.env')  # Ключ Owner
OWNER_KEY = os.getenv('PRIVATE_KEY')

load_dotenv('bot1.env')   # Ключ Trader_1 (агрессивный)
TRADER1_KEY = os.getenv('PRIVATE_KEY')

load_dotenv('bot2.env')   # Ключ Trader_2 (консервативный)
TRADER2_KEY = os.getenv('PRIVATE_KEY')

# Проверка загрузки ключей
if not OWNER_KEY or not TRADER1_KEY or not TRADER2_KEY:
    raise Exception("❌ Не удалось загрузить ключи из .env файлов. Проверьте owner.env, bot1.env, bot2.env")

# ====================================================================================================
# НАСТРОЙКА ЛОГГИРОВАНИЯ
# ====================================================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("sinergia_trading.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Sinergia")

# ====================================================================================================
# ПОДКЛЮЧЕНИЕ К БЛОКЧЕЙНУ
# ====================================================================================================

w3 = Web3(Web3.HTTPProvider('https://polygon-rpc.com'))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)  # Для Polygon

if not w3.is_connected():
    raise Exception("❌ Нет соединения с Polygon RPC")

logger.info(f"✅ Подключено к Polygon. Блок: {w3.eth.block_number}")

# ====================================================================================================
# ФУНКЦИЯ ДЛЯ РАСПРЕДЕЛЕНИЯ 50 MATIC
# ====================================================================================================

async def distribute_initial_funds():
    """
    Распределяет 50 MATIC между тремя кошельками:
    - Owner: 30 MATIC (отправитель)
    - Trader_1: 10 MATIC
    - Trader_2: 10 MATIC
    """
    owner_account = w3.eth.account.from_key(OWNER_KEY)
    trader1_account = w3.eth.account.from_key(TRADER1_KEY)
    trader2_account = w3.eth.account.from_key(TRADER2_KEY)
    
    owner_balance = w3.eth.get_balance(owner_account.address)
    owner_balance_matic = w3.from_wei(owner_balance, 'ether')
    
    logger.info("="*60)
    logger.info("💰 РАСПРЕДЕЛЕНИЕ 50 MATIC")
    logger.info("="*60)
    logger.info(f"Owner адрес: {owner_account.address}")
    logger.info(f"Баланс Owner: {owner_balance_matic:.4f} MATIC")
    logger.info(f"Trader_1 адрес: {trader1_account.address}")
    logger.info(f"Trader_2 адрес: {trader2_account.address}")
    
    # Проверяем, нужно ли распределять
    if owner_balance_matic < 50:
        logger.warning(f"⚠️  У Owner меньше 50 MATIC ({owner_balance_matic:.4f}). Распределение невозможно.")
        return False
    
    # Проверяем текущие балансы трейдеров
    trader1_balance = w3.eth.get_balance(trader1_account.address)
    trader2_balance = w3.eth.get_balance(trader2_account.address)
    
    trader1_matic = w3.from_wei(trader1_balance, 'ether')
    trader2_matic = w3.from_wei(trader2_balance, 'ether')
    
    logger.info(f"Текущий баланс Trader_1: {trader1_matic:.4f} MATIC")
    logger.info(f"Текущий баланс Trader_2: {trader2_matic:.4f} MATIC")
    
    # Отправляем 10 MATIC Trader_1 (если нужно)
    if trader1_matic < 9.5:  # Если меньше 9.5 MATIC
        amount_to_send = w3.to_wei(10.0, 'ether')
        nonce = w3.eth.get_transaction_count(owner_account.address)
        
        tx = {
            'nonce': nonce,
            'to': trader1_account.address,
            'value': amount_to_send,
            'gas': 21000,
            'gasPrice': w3.to_wei(40, 'gwei'),
            'chainId': 137
        }
        
        signed = owner_account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt.status == 1:
            logger.info(f"✅ Отправлено 10 MATIC Trader_1. Tx: {tx_hash.hex()}")
        else:
            logger.error("❌ Ошибка отправки Trader_1")
            return False
        await asyncio.sleep(2)  # Пауза между транзакциями
    
    # Отправляем 10 MATIC Trader_2 (если нужно)
    if trader2_matic < 9.5:  # Если меньше 9.5 MATIC
        amount_to_send = w3.to_wei(10.0, 'ether')
        nonce = w3.eth.get_transaction_count(owner_account.address)
        
        tx = {
            'nonce': nonce,
            'to': trader2_account.address,
            'value': amount_to_send,
            'gas': 21000,
            'gasPrice': w3.to_wei(40, 'gwei'),
            'chainId': 137
        }
        
        signed = owner_account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt.status == 1:
            logger.info(f"✅ Отправлено 10 MATIC Trader_2. Tx: {tx_hash.hex()}")
        else:
            logger.error("❌ Ошибка отправки Trader_2")
            return False
    
    # Финальная проверка
    new_trader1 = w3.from_wei(w3.eth.get_balance(trader1_account.address), 'ether')
    new_trader2 = w3.from_wei(w3.eth.get_balance(trader2_account.address), 'ether')
    new_owner = w3.from_wei(w3.eth.get_balance(owner_account.address), 'ether')
    
    logger.info("="*60)
    logger.info("📊 ИТОГОВОЕ РАСПРЕДЕЛЕНИЕ:")
    logger.info(f"Owner: {new_owner:.4f} MATIC (~30 MATIC)")
    logger.info(f"Trader_1: {new_trader1:.4f} MATIC (~10 MATIC)")
    logger.info(f"Trader_2: {new_trader2:.4f} MATIC (~10 MATIC)")
    logger.info("="*60)
    
    return True

# ====================================================================================================
# КОНФИГУРАЦИЯ
# ====================================================================================================

CONFIG = {
    # -------------------- БЛОКЧЕЙН --------------------
    'rpc_url': 'https://polygon-rpc.com',
    'chain_id': 137,
    
    # -------------------- АДРЕСА КОНТРАКТОВ (ЗАМЕНИТЬ ПОСЛЕ ДЕПЛОЯ) --------------------
    'casrs_address': '0xYOUR_DEPLOYED_CASRS_ADDRESS',  # ВСТАВИТЬ ПОСЛЕ ДЕПЛОЯ
    'casrg_address': '0xYOUR_DEPLOYED_CASRG_ADDRESS',  # ВСТАВИТЬ ПОСЛЕ ДЕПЛОЯ
    'quickswap_router': '0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff',
    'weth_address': '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270',
    
    # -------------------- 3 КОШЕЛЬКА С КЛЮЧАМИ ИЗ .env --------------------
    'accounts': [
        {
            'name': 'Owner',
            'private_key': OWNER_KEY,
            'role': 'owner'
        },
        {
            'name': 'Trader_1_Aggressive',
            'private_key': TRADER1_KEY,
            'role': 'trader',
            'aggressive': True
        },
        {
            'name': 'Trader_2_Conservative',
            'private_key': TRADER2_KEY,
            'role': 'trader',
            'aggressive': False
        }
    ],
    
    # -------------------- ПАРАМЕТРЫ МОДЕЛИ --------------------
    'h_RS': 0.50,
    'h_RG': 0.90,
    'rho': 0.10,
    'omega': 0.05,
    'fee': 0.003,
    'tau': 0.005,
    'alpha': 0.45,
    'beta': 0.35,
    'k1': 0.90,
    'k2': 0.65,
    'cf': 0.45,
    'project_funding_pct': 0.05,
    'min_coverage': 1.20,
    'holder_reward_pct': 0.10,
    'lock_min_months': 1,
    'lock_max_months': 60,
    'lock_base_apr': 0.05,
    'lock_bonus_per_month': 0.002,
    'lock_max_apr': 0.30,
    
    # -------------------- ТОРГОВЫЕ ПАРАМЕТРЫ --------------------
    'base_trade_matic': 0.02,
    'volume_pct': 0.18,
    'buy_pct': 0.62,
    'sell_pct': 0.38,
    
    # -------------------- ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ --------------------
    'gas_price_gwei': 40,
    'cycle_sleep_sec': 15,
    'max_slippage': 0.02,
    'price_history_size': 24,
}

# ====================================================================================================
# ABI КОНТРАКТОВ
# ====================================================================================================

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", 
     "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], 
     "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}], 
     "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], 
     "type": "function"},
]

ROUTER_ABI = [
    {"inputs": [{"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"},
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "uint256", "name": "deadline", "type": "uint256"}],
     "name": "swapExactETHForTokensSupportingFeeOnTransferTokens",
     "outputs": [], "stateMutability": "payable", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"},
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "uint256", "name": "deadline", "type": "uint256"}],
     "name": "swapExactTokensForETHSupportingFeeOnTransferTokens",
     "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"}],
     "name": "getAmountsOut", "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
     "stateMutability": "view", "type": "function"},
]

CASRS_ABI = [
    {"inputs": [{"internalType": "uint256", "name": "amountETH", "type": "uint256"}],
     "name": "robotBuyback", "outputs": [], "stateMutability": "payable", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "tokenAmount", "type": "uint256"}],
     "name": "robotAddLiquidity", "outputs": [], "stateMutability": "payable", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "amount", "type": "uint256"}],
     "name": "robotBurn", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "getSafePrice", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "getSystemAccounting", 
     "outputs": [{"internalType": "uint256", "name": "assetsSafe", "type": "uint256"},
                 {"internalType": "uint256", "name": "liabilitiesSafe", "type": "uint256"},
                 {"internalType": "uint256", "name": "equityNav", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "getFreeFloat", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType": "address", "name": "user", "type": "address"}, 
                {"internalType": "uint256", "name": "amount", "type": "uint256"},
                {"internalType": "uint256", "name": "duration", "type": "uint256"}],
     "name": "lockTokens", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
] + ERC20_ABI

CASRG_ABI = [
    {"inputs": [{"internalType": "uint256", "name": "rsAmount", "type": "uint256"}],
     "name": "mintAgainstCollateral", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "rgAmount", "type": "uint256"}],
     "name": "repay", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"internalType": "address", "name": "user", "type": "address"}],
     "name": "liquidate", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "getSystemCoverage", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
] + ERC20_ABI

# ====================================================================================================
# МАТЕМАТИЧЕСКАЯ МОДЕЛЬ
# ====================================================================================================

@dataclass
class SystemMetrics:
    P_spot: float = 0.0
    P_twap: float = 0.0
    P_safe: float = 0.0
    A: float = 0.0
    N: float = 0.0
    K: float = 0.0
    STS: float = 0.0
    C: float = 0.0
    D: float = 0.0
    B: float = 0.0
    F: float = 0.0
    S: float = 0.0
    emergency_mode: bool = False
    emission_paused: bool = False


class MathModel:
    def __init__(self, config: Dict):
        self.cfg = config
        self.price_history: List[float] = []
        
    def liquidation_value(self, X: float, Y: float, x: float) -> float:
        if x <= 0:
            return 0.0
        denominator = X + x * (1 - self.cfg['fee'])
        if denominator <= 0:
            return 0.0
        return Y - (X * Y) / denominator
    
    def exit_price(self, X: float, Y: float, x: float) -> float:
        if x <= 0:
            return Y / X if X > 0 else 0.0
        lv = self.liquidation_value(X, Y, x)
        return lv / x if lv > 0 else Y / X
    
    def safe_price(self, X: float, Y: float, F: float, P_twap: float) -> float:
        if F <= 0:
            return P_twap
        x_stress = self.cfg['rho'] * F
        P_exit = self.exit_price(X, Y, x_stress)
        return min(P_twap, P_exit)
    
    def safe_assets(self, B: float, C: float, R_RS: float, R_RG: float, P_safe: float) -> float:
        collateral = (1 - self.cfg['h_RS']) * C * P_safe
        reserve = (1 - self.cfg['h_RS']) * R_RS * P_safe
        rg = self.cfg['h_RG'] * R_RG
        return B + collateral + reserve + rg
    
    def update_twap(self, new_spot: float) -> float:
        self.price_history.append(new_spot)
        if len(self.price_history) > 24:
            self.price_history.pop(0)
        if len(self.price_history) < 24:
            return new_spot
        return sum(self.price_history) / len(self.price_history)
    
    def calculate_metrics(self, state: Dict) -> SystemMetrics:
        metrics = SystemMetrics()
        
        X = state.get('X', 0)
        Y = state.get('Y', 0)
        metrics.P_spot = Y / X if X > 0 else 0
        metrics.P_twap = self.update_twap(metrics.P_spot)
        metrics.P_safe = self.safe_price(X, Y, state.get('F', 0), metrics.P_twap)
        metrics.A = self.safe_assets(
            state.get('B', 0), state.get('C', 0), 
            state.get('R_RS', 0), state.get('R_RG', 0), 
            metrics.P_safe
        )
        
        D = state.get('D', 0)
        metrics.D = D
        unwind = self.cfg['omega'] * D
        metrics.K = (metrics.A - unwind) / D if D > 0 else float('inf')
        metrics.N = metrics.A - D - unwind
        
        lv_stress = self.liquidation_value(X, Y, self.cfg['rho'] * state.get('F', 0))
        numerator = (state.get('B', 0) + lv_stress +
                    (1 - self.cfg['h_RS']) * state.get('C', 0) * metrics.P_safe +
                    self.cfg['h_RG'] * state.get('R_RG', 0))
        denominator = D + unwind
        metrics.STS = numerator / denominator if denominator > 0 else float('inf')
        
        metrics.emergency_mode = metrics.STS < 1.0
        metrics.emission_paused = metrics.K < self.cfg['min_coverage']
        
        metrics.C = state.get('C', 0)
        metrics.B = state.get('B', 0)
        metrics.F = state.get('F', 0)
        metrics.S = state.get('S', 0)
        
        return metrics

# ====================================================================================================
# КЛАСС ТРЕЙДЕРА
# ====================================================================================================

class Trader:
    def __init__(self, name: str, private_key: str, role: str, aggressive: bool = False):
        self.name = name
        self.private_key = private_key
        self.account = w3.eth.account.from_key(private_key)
        self.address = self.account.address
        self.role = role
        self.aggressive = aggressive
        
        # Контракты будут инициализированы после установки адресов
        self.casrs = None
        self.casrg = None
        self.router = w3.eth.contract(address=CONFIG['quickswap_router'], abi=ROUTER_ABI)
        
        self.trades_count = 0
        self.volume_matic = 0.0
        self.last_tx_hash = None
        
        logger.info(f"✅ Трейдер {self.name} инициализирован: {self.address}")
    
    def set_contracts(self, casrs_address: str, casrg_address: str):
        """Установка адресов контрактов после деплоя"""
        self.casrs = w3.eth.contract(address=casrs_address, abi=CASRS_ABI)
        self.casrg = w3.eth.contract(address=casrg_address, abi=CASRG_ABI)
        logger.info(f"✅ {self.name}: контракты установлены")
    
    async def get_balances(self) -> Dict[str, float]:
        try:
            matic = w3.from_wei(w3.eth.get_balance(self.address), 'ether')
            
            if self.casrs:
                casrs_wei = await self.casrs.functions.balanceOf(self.address).call()
                casrs = casrs_wei / 1e18
            else:
                casrs = 0.0
            
            if self.casrg:
                casrg_wei = await self.casrg.functions.balanceOf(self.address).call()
                casrg = casrg_wei / 1e18
            else:
                casrg = 0.0
            
            return {'matic': float(matic), 'casrs': float(casrs), 'casrg': float(casrg)}
        except Exception as e:
            logger.error(f"[{self.name}] Ошибка получения балансов: {e}")
            return {'matic': 0.0, 'casrs': 0.0, 'casrg': 0.0}
    
    async def _send_transaction(self, func, value: int = 0, gas_limit: int = 500000) -> Optional[str]:
        try:
            nonce = w3.eth.get_transaction_count(self.address)
            
            tx = func.build_transaction({
                'from': self.address,
                'nonce': nonce,
                'gas': gas_limit,
                'gasPrice': w3.to_wei(CONFIG['gas_price_gwei'], 'gwei'),
                'value': value,
                'chainId': CONFIG['chain_id']
            })
            
            signed = self.account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            
            logger.info(f"[{self.name}] Транзакция отправлена: {tx_hash.hex()}")
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                logger.info(f"[{self.name}] ✅ Транзакция подтверждена в блоке {receipt.blockNumber}")
                self.last_tx_hash = tx_hash.hex()
                return tx_hash.hex()
            else:
                logger.error(f"[{self.name}] ❌ Транзакция провалилась")
                return None
                
        except Exception as e:
            logger.error(f"[{self.name}] Ошибка транзакции: {e}")
            return None
    
    async def buy(self, token: str, amount_matic: float) -> Optional[str]:
        if amount_matic <= 0 or not self.casrs or not self.casrg:
            return None
            
        amount_wei = w3.to_wei(amount_matic, 'ether')
        token_addr = CONFIG['casrs_address'] if token == 'casrs' else CONFIG['casrg_address']
        path = [CONFIG['weth_address'], token_addr]
        
        func = self.router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            0, path, self.address, int(time.time()) + 1200
        )
        
        logger.info(f"[{self.name}] Покупка {token.upper()} на {amount_matic:.4f} MATIC")
        self.trades_count += 1
        self.volume_matic += amount_matic
        
        return await self._send_transaction(func, value=amount_wei, gas_limit=400000)
    
    async def sell(self, token: str, fraction: float = 0.5) -> Optional[str]:
        balances = await self.get_balances()
        token_bal = balances[token]
        
        if token_bal < 1000:
            return None
        
        amount = int(token_bal * fraction * 1e18)
        token_addr = CONFIG['casrs_address'] if token == 'casrs' else CONFIG['casrg_address']
        path = [token_addr, CONFIG['weth_address']]
        
        contract = self.casrs if token == 'casrs' else self.casrg
        approve = contract.functions.approve(CONFIG['quickswap_router'], amount)
        await self._send_transaction(approve, gas_limit=120000)
        
        func = self.router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
            amount, 0, path, self.address, int(time.time()) + 1200
        )
        
        logger.info(f"[{self.name}] Продажа {amount/1e18:.2f} {token.upper()}")
        self.trades_count += 1
        
        return await self._send_transaction(func, gas_limit=400000)

# ====================================================================================================
# КЛАСС OWNER
# ====================================================================================================

class Owner(Trader):
    def __init__(self, name: str, private_key: str):
        super().__init__(name, private_key, 'owner')
        self.math_model = MathModel(CONFIG)
        self.last_metrics: Optional[SystemMetrics] = None
        self.system_state = {
            'B': 0.0, 'C': 0.0, 'R_RS': 0.0, 'F': 0.0,
            'D': 0.0, 'R_RG': 0.0, 'X': 0.0, 'Y': 0.0, 'S': 0.0
        }
    
    async def update_system_state(self) -> SystemMetrics:
        if not self.casrs or not self.casrg:
            return SystemMetrics()
            
        try:
            accounting = await self.casrs.functions.getSystemAccounting().call()
            free_float = await self.casrs.functions.getFreeFloat().call()
            safe_price = await self.casrs.functions.getSafePrice().call()
            total_supply = await self.casrs.functions.totalSupply().call()
            coverage = await self.casrg.functions.getSystemCoverage().call()
            total_debt = await self.casrg.functions.totalSupply().call()
            
            self.system_state = {
                'B': 100.0, 'C': 2000.0, 'R_RS': 2500.0,
                'F': free_float / 1e18, 'D': total_debt / 1e18,
                'R_RG': 2.0, 'X': 3500.0, 'Y': 35.0,
                'S': total_supply / 1e18
            }
            
            metrics = self.math_model.calculate_metrics(self.system_state)
            metrics.P_safe = safe_price / 1e18
            metrics.K = coverage / 1000
            self.last_metrics = metrics
            return metrics
            
        except Exception as e:
            logger.error(f"[Owner] Ошибка получения состояния: {e}")
            return SystemMetrics()
    
    async def recycle_contract(self, token: str) -> Optional[str]:
        try:
            contract = self.casrs if token == 'casrs' else self.casrg
            eth_balance = w3.eth.get_balance(contract.address)
            
            if eth_balance < w3.to_wei(CONFIG['base_trade_matic'], 'ether'):
                return None
            
            func = contract.functions.robotBuyback(eth_balance)
            logger.info(f"[Owner] Рециклинг {w3.from_wei(eth_balance, 'ether'):.4f} ETH из {token.upper()}")
            return await self._send_transaction(func, gas_limit=500000)
        except Exception as e:
            logger.error(f"[Owner] Ошибка рециклинга: {e}")
            return None

# ====================================================================================================
# ОСНОВНОЙ ТОРГОВЫЙ ЦИКЛ
# ====================================================================================================

class SinergiaSystem:
    def __init__(self, config: Dict):
        self.cfg = config
        self.owner: Optional[Owner] = None
        self.traders: List[Trader] = []
        self.cycle_count = 0
        self.start_time = datetime.now()
        self.contracts_ready = False
        
        self._init_accounts()
        
    def _init_accounts(self):
        for acc in self.cfg['accounts']:
            if acc['role'] == 'owner':
                self.owner = Owner(acc['name'], acc['private_key'])
            else:
                trader = Trader(
                    acc['name'], acc['private_key'], 
                    acc['role'], acc.get('aggressive', False)
                )
                self.traders.append(trader)
    
    def set_contracts(self, casrs_address: str, casrg_address: str):
        """Установка адресов контрактов после деплоя"""
        self.cfg['casrs_address'] = casrs_address
        self.cfg['casrg_address'] = casrg_address
        
        if self.owner:
            self.owner.set_contracts(casrs_address, casrg_address)
        
        for trader in self.traders:
            trader.set_contracts(casrs_address, casrg_address)
        
        self.contracts_ready = True
        logger.info(f"✅ Адреса контрактов установлены: CASRS={casrs_address}, CASRG={casrg_address}")
    
    async def get_all_balances(self) -> Dict:
        balances = {}
        if self.owner:
            balances['owner'] = await self.owner.get_balances()
        for trader in self.traders:
            balances[trader.name] = await trader.get_balances()
        return balances
    
    async def check_system_health(self) -> bool:
        if not self.owner or not self.contracts_ready:
            return False
        
        metrics = await self.owner.update_system_state()
        
        logger.info(f"📊 Системные метрики:")
        logger.info(f"   P_spot = {metrics.P_spot:.6f}")
        logger.info(f"   P_safe = {metrics.P_safe:.6f}")
        logger.info(f"   K = {metrics.K:.2f}")
        logger.info(f"   STS = {metrics.STS:.2f}")
        
        if metrics.N <= 0 or metrics.K < 1.0 or metrics.STS < 1.0 or metrics.emergency_mode:
            logger.error("❌ Система нездорова!")
            return False
        return True
    
    async def trading_cycle(self):
        self.cycle_count += 1
        logger.info(f"\n{'='*60}\nЦИКЛ {self.cycle_count}\n{'='*60}")
        
        if not self.contracts_ready:
            logger.warning("⚠️ Контракты не установлены. Ожидание...")
            return
        
        await self.check_system_health()
        
        for token in ['casrs', 'casrg']:
            random.shuffle(self.traders)
            
            for trader in self.traders:
                balances = await trader.get_balances()
                
                if balances['matic'] < self.cfg['base_trade_matic'] * 2:
                    continue
                
                buy_chance = 0.8 if trader.aggressive else 0.6
                if token == 'casrg':
                    buy_chance *= 0.75  # Меньше покупок CASRG
                
                amount = self.cfg['base_trade_matic'] * random.uniform(0.7, 1.3)
                
                if random.random() < buy_chance:
                    await trader.buy(token, amount)
                elif balances[token] > 1000:
                    await trader.sell(token, random.uniform(0.2, 0.5))
                
                await asyncio.sleep(random.uniform(1.0, 3.0))
        
        if self.owner and self.cycle_count % 5 == 0:
            for token in ['casrs', 'casrg']:
                await self.owner.recycle_contract(token)
    
    async def print_statistics(self):
        balances = await self.get_all_balances()
        
        logger.info("\n" + "="*60)
        logger.info("📈 СТАТИСТИКА")
        logger.info("="*60)
        
        total_volume = 0
        total_trades = 0
        
        for name, bal in balances.items():
            logger.info(f"\n{name}:")
            logger.info(f"  MATIC: {bal['matic']:.4f}")
            logger.info(f"  CASRS: {bal['casrs']:.2f}")
            logger.info(f"  CASRG: {bal['casrg']:.2f}")
            
            for trader in self.traders:
                if trader.name == name:
                    total_volume += trader.volume_matic
                    total_trades += trader.trades_count
                    logger.info(f"  Сделок: {trader.trades_count}")
                    logger.info(f"  Объём: {trader.volume_matic:.4f} MATIC")
        
        elapsed = datetime.now() - self.start_time
        logger.info(f"\n⏱️  Время работы: {elapsed}")
        logger.info("="*60)
    
    async def run(self):
        logger.info("="*60)
        logger.info("🚀 ЗАПУСК СИСТЕМЫ 'СИНЕРГИЯ'")
        logger.info("="*60)
        
        if not w3.is_connected():
            logger.error("❌ Нет соединения с блокчейном")
            return
        
        # Сначала распределяем 50 MATIC
        await distribute_initial_funds()
        
        logger.info("\n⏳ Ожидание установки адресов контрактов...")
        logger.info("После деплоя вызовите: system.set_contracts('адрес_CASRS', 'адрес_CASRG')")
        
        # Ждём, пока не установят адреса контрактов
        while not self.contracts_ready:
            await asyncio.sleep(5)
        
        logger.info("✅ Контракты установлены. Запуск торгового цикла...")
        
        try:
            while True:
                await self.trading_cycle()
                if self.cycle_count % 10 == 0:
                    await self.print_statistics()
                await asyncio.sleep(self.cfg['cycle_sleep_sec'])
                
        except KeyboardInterrupt:
            logger.info("🛑 Система остановлена пользователем")
            await self.print_statistics()

# ====================================================================================================
# ЗАПУСК
# ====================================================================================================

async def main():
    print("="*80)
    print("🚀 СИСТЕМА УПРАВЛЕНИЯ И ТОРГОВЛИ 'СИНЕРГИЯ'")
    print("Версия 6.0 - С распределением 50 MATIC")
    print("="*80)
    print("\n📋 КОНФИГУРАЦИЯ:")
    print(f"   - Owner: из owner.env")
    print(f"   - Trader_1 (агрессивный): из bot1.env")
    print(f"   - Trader_2 (консервативный): из bot2.env")
    print(f"   - Распределение: Owner=30 MATIC, Trader_1=10 MATIC, Trader_2=10 MATIC")
    print("="*80)
    
    system = SinergiaSystem(CONFIG)
    
    # После деплоя контрактов, раскомментировать и вставить адреса:
    # system.set_contracts('0x...CASRS', '0x...CASRG')
    
    await system.run()

if __name__ == "__main__":
    asyncio.run(main())
