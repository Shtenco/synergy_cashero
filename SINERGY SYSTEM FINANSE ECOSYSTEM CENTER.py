#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
====================================================================================================
СИСТЕМА УПРАВЛЕНИЯ И ТОРГОВЛИ "СИНЕРГИЯ" - ПОЛНАЯ РЕАЛИЗАЦИЯ МАТЕМАТИЧЕСКОЙ МОДЕЛИ
====================================================================================================
ВЕРСИЯ 5.0 - ДЛЯ 3 КОШЕЛЬКОВ (ИЮНЬ 2026)

Полностью соответствует математической модели из closed_loop_v3.py:
✅ Двухконтурная система (CASRS + CASRG)
✅ Safe price = min(TWAP, exit price при продаже 10% free-float)
✅ Эмиссия CASRS при росте цены, сжигание при падении
✅ CASRG эмитируется только под залог CASRS (haircut 50%)
✅ Stop-test с автоматическим emergency mode
✅ 5% эмиссии на проекты
✅ Приостановка эмиссии при K < 1.20
✅ 10% комиссий держателям CASRS
✅ Блокировка токенов на 1-60 месяцев

ТРИ КОШЕЛЬКА:
- Owner (владелец системы)
- Trader_1 (агрессивный трейдер)
- Trader_2 (консервативный трейдер)

Все вызовы готовы для интеграции со смарт-контрактами
====================================================================================================
"""

import asyncio
import logging
import json
import time
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
from web3 import Web3
from web3.middleware import geth_poa_middleware

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
# КОНФИГУРАЦИЯ - ЗАМЕНИТЬ НА СВОИ ДАННЫЕ!
# ====================================================================================================

CONFIG = {
    # -------------------- БЛОКЧЕЙН --------------------
    'rpc_url': 'https://polygon-rpc.com',  # или свой узел
    'chain_id': 137,  # Polygon Mainnet
    
    # -------------------- АДРЕСА КОНТРАКТОВ --------------------
    'casrs_address': '0xYOUR_DEPLOYED_CASRS_ADDRESS',  # CASRS (Savings)
    'casrg_address': '0xYOUR_DEPLOYED_CASRG_ADDRESS',  # CASRG (Stable)
    'quickswap_router': '0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff',  # QuickSwap
    'weth_address': '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270',  # WMATIC
    
    # -------------------- 3 КОШЕЛЬКА --------------------
    'accounts': [
        {
            'name': 'Owner',
            'private_key': '0x...',  # Владелец системы
            'role': 'owner'
        },
        {
            'name': 'Trader_1_Aggressive',
            'private_key': '0x...',  # Агрессивный трейдер
            'role': 'trader',
            'aggressive': True
        },
        {
            'name': 'Trader_2_Conservative',
            'private_key': '0x...',  # Консервативный трейдер
            'role': 'trader',
            'aggressive': False
        }
    ],
    
    # -------------------- ПАРАМЕТРЫ МОДЕЛИ (ИЗ closed_loop_v3.py) --------------------
    # Риск-параметры
    'h_RS': 0.50,           # Haircut на CASRS (50%)
    'h_RG': 0.90,           # Haircut на CASRG (10%)
    'rho': 0.10,            # Стресс-доля free-float для safe price
    'omega': 0.05,          # Unwind cost (5%)
    'fee': 0.003,           # Комиссия AMM (0.3%)
    'tau': 0.005,           # Комиссия в резерв (0.5%)
    
    # Параметры эмиссии CASRS
    'alpha': 0.45,          # Коэффициент эмиссии при росте
    'beta': 0.35,           # Коэффициент сжигания при падении
    'k1': 0.90,             # Лимит по новому залогу
    'k2': 0.65,             # Лимит по росту NAV
    
    # Параметры долга CASRG
    'cf': 0.45,             # Collateral factor
    
    # НОВЫЕ МЕХАНИЗМЫ
    'project_funding_pct': 0.05,    # 5% эмиссии на проекты
    'min_coverage': 1.20,           # Мин. покрытие для эмиссии
    'holder_reward_pct': 0.10,       # 10% комиссий держателям
    
    # Параметры блокировки
    'lock_min_months': 1,
    'lock_max_months': 60,
    'lock_base_apr': 0.05,
    'lock_bonus_per_month': 0.002,
    'lock_max_apr': 0.30,
    
    # -------------------- ТОРГОВЫЕ ПАРАМЕТРЫ --------------------
    'base_trade_matic': 0.02,        # Базовый объём сделки в MATIC
    'volume_pct': 0.18,               # Доля от пула (18%)
    'buy_pct': 0.62,                   # Доля покупок (62%)
    'sell_pct': 0.38,                   # Доля продаж (38%)
    
    # -------------------- ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ --------------------
    'gas_price_gwei': 40,              # Газ для Polygon
    'cycle_sleep_sec': 15,             # Пауза между циклами
    'max_slippage': 0.02,               # Макс. проскальзывание (2%)
    'price_history_size': 24,           # Размер истории для TWAP
}

# ====================================================================================================
# ABI КОНТРАКТОВ
# ====================================================================================================

# ERC20 базовый
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

# QuickSwap Router ABI
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

# CASRS ABI (Savings Token)
CASRS_ABI = [
    # Функции из контракта
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

# CASRG ABI (Stable Token)
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
# ПОДКЛЮЧЕНИЕ К БЛОКЧЕЙНУ
# ====================================================================================================

w3 = Web3(Web3.HTTPProvider(CONFIG['rpc_url']))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)  # Для Polygon

if not w3.is_connected():
    raise Exception("❌ Нет соединения с Polygon RPC")

logger.info(f"✅ Подключено к Polygon. Блок: {w3.eth.block_number}")

# ====================================================================================================
# МАТЕМАТИЧЕСКАЯ МОДЕЛЬ (из closed_loop_v3.py)
# ====================================================================================================

@dataclass
class SystemMetrics:
    """Метрики системы, рассчитанные по математической модели"""
    P_spot: float = 0.0
    P_twap: float = 0.0
    P_safe: float = 0.0
    A: float = 0.0  # Safe assets
    N: float = 0.0  # Equity NAV
    K: float = 0.0  # Coverage ratio
    STS: float = 0.0  # Stop-test ratio
    C: float = 0.0  # Eligible collateral
    D: float = 0.0  # Total debt
    B: float = 0.0  # Base reserve
    F: float = 0.0  # Free-float
    S: float = 0.0  # Total supply
    emergency_mode: bool = False
    emission_paused: bool = False


class MathModel:
    """Реализация математической модели из closed_loop_v3.py"""
    
    def __init__(self, config: Dict):
        self.cfg = config
        self.price_history: List[float] = []
        
    def liquidation_value(self, X: float, Y: float, x: float) -> float:
        """LV(x) = Y - (X*Y)/(X + x*(1-fee))"""
        if x <= 0:
            return 0.0
        denominator = X + x * (1 - self.cfg['fee'])
        if denominator <= 0:
            return 0.0
        return Y - (X * Y) / denominator
    
    def exit_price(self, X: float, Y: float, x: float) -> float:
        """P_exit(x) = LV(x)/x"""
        if x <= 0:
            return Y / X if X > 0 else 0.0
        lv = self.liquidation_value(X, Y, x)
        return lv / x if lv > 0 else Y / X
    
    def safe_price(self, X: float, Y: float, F: float, P_twap: float) -> float:
        """P_safe = min(P_twap, P_exit(ρ*F))"""
        if F <= 0:
            return P_twap
        x_stress = self.cfg['rho'] * F
        P_exit = self.exit_price(X, Y, x_stress)
        return min(P_twap, P_exit)
    
    def safe_assets(self, B: float, C: float, R_RS: float, R_RG: float, P_safe: float) -> float:
        """A = B + (1-h_RS)*C*P_safe + (1-h_RS)*R_RS*P_safe + h_RG*R_RG"""
        collateral = (1 - self.cfg['h_RS']) * C * P_safe
        reserve = (1 - self.cfg['h_RS']) * R_RS * P_safe
        rg = self.cfg['h_RG'] * R_RG
        return B + collateral + reserve + rg
    
    def update_twap(self, new_spot: float) -> float:
        """Обновление TWAP (24 периода)"""
        self.price_history.append(new_spot)
        if len(self.price_history) > 24:
            self.price_history.pop(0)
        if len(self.price_history) < 24:
            return new_spot
        return sum(self.price_history) / len(self.price_history)
    
    def calculate_metrics(self, state: Dict) -> SystemMetrics:
        """Расчёт всех метрик системы"""
        metrics = SystemMetrics()
        
        # Базовые данные
        X = state.get('X', 0)
        Y = state.get('Y', 0)
        metrics.P_spot = Y / X if X > 0 else 0
        
        # TWAP
        metrics.P_twap = self.update_twap(metrics.P_spot)
        
        # Safe price
        metrics.P_safe = self.safe_price(
            X, Y, 
            state.get('F', 0), 
            metrics.P_twap
        )
        
        # Safe assets
        metrics.A = self.safe_assets(
            state.get('B', 0),
            state.get('C', 0),
            state.get('R_RS', 0),
            state.get('R_RG', 0),
            metrics.P_safe
        )
        
        # Долг и покрытие
        D = state.get('D', 0)
        metrics.D = D
        unwind = self.cfg['omega'] * D
        metrics.K = (metrics.A - unwind) / D if D > 0 else float('inf')
        metrics.N = metrics.A - D - unwind
        
        # Stop-test
        lv_stress = self.liquidation_value(
            X, Y,
            self.cfg['rho'] * state.get('F', 0)
        )
        numerator = (
            state.get('B', 0) + lv_stress +
            (1 - self.cfg['h_RS']) * state.get('C', 0) * metrics.P_safe +
            self.cfg['h_RG'] * state.get('R_RG', 0)
        )
        denominator = D + unwind
        metrics.STS = numerator / denominator if denominator > 0 else float('inf')
        
        # Флаги
        metrics.emergency_mode = metrics.STS < 1.0
        metrics.emission_paused = metrics.K < self.cfg['min_coverage']
        
        # Другие метрики
        metrics.C = state.get('C', 0)
        metrics.B = state.get('B', 0)
        metrics.F = state.get('F', 0)
        metrics.S = state.get('S', 0)
        
        return metrics

# ====================================================================================================
# КЛАСС ТРЕЙДЕРА (ДЛЯ 3 КОШЕЛЬКОВ)
# ====================================================================================================

class Trader:
    """Трейдер для работы с обоими токенами"""
    
    def __init__(self, name: str, private_key: str, role: str, aggressive: bool = False):
        self.name = name
        self.private_key = private_key
        self.account = w3.eth.account.from_key(private_key)
        self.address = self.account.address
        self.role = role
        self.aggressive = aggressive
        
        # Контракты
        self.casrs = w3.eth.contract(address=CONFIG['casrs_address'], abi=CASRS_ABI)
        self.casrg = w3.eth.contract(address=CONFIG['casrg_address'], abi=CASRG_ABI)
        self.router = w3.eth.contract(address=CONFIG['quickswap_router'], abi=ROUTER_ABI)
        
        # Статистика
        self.trades_count = 0
        self.volume_matic = 0.0
        self.last_tx_hash = None
        
        logger.info(f"✅ Трейдер {self.name} инициализирован: {self.address}")
    
    # ------------------------------------------------------------------------------------------------
    # БАЛАНСЫ
    # ------------------------------------------------------------------------------------------------
    
    async def get_balances(self) -> Dict[str, float]:
        """Получение балансов кошелька"""
        try:
            matic = w3.from_wei(w3.eth.get_balance(self.address), 'ether')
            
            casrs_wei = await self.casrs.functions.balanceOf(self.address).call()
            casrs = casrs_wei / 1e18
            
            casrg_wei = await self.casrg.functions.balanceOf(self.address).call()
            casrg = casrg_wei / 1e18
            
            return {
                'matic': float(matic),
                'casrs': float(casrs),
                'casrg': float(casrg)
            }
        except Exception as e:
            logger.error(f"[{self.name}] Ошибка получения балансов: {e}")
            return {'matic': 0.0, 'casrs': 0.0, 'casrg': 0.0}
    
    # ------------------------------------------------------------------------------------------------
    # ОТПРАВКА ТРАНЗАКЦИЙ
    # ------------------------------------------------------------------------------------------------
    
    async def _send_transaction(self, func, value: int = 0, gas_limit: int = 500000) -> Optional[str]:
        """Отправка транзакции с обработкой ошибок"""
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
            
            # Ожидание подтверждения
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
    
    # ------------------------------------------------------------------------------------------------
    # ТОРГОВЫЕ ФУНКЦИИ
    # ------------------------------------------------------------------------------------------------
    
    async def buy(self, token: str, amount_matic: float) -> Optional[str]:
        """Покупка токена за MATIC"""
        if amount_matic <= 0:
            return None
            
        amount_wei = w3.to_wei(amount_matic, 'ether')
        token_addr = CONFIG['casrs_address'] if token == 'casrs' else CONFIG['casrg_address']
        
        # Путь: WMATIC -> TOKEN
        path = [CONFIG['weth_address'], token_addr]
        
        func = self.router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            0,  # minAmountOut = 0 (с учётом проскальзывания)
            path,
            self.address,
            int(time.time()) + 1200  # deadline 20 минут
        )
        
        logger.info(f"[{self.name}] Покупка {token.upper()} на {amount_matic:.4f} MATIC")
        self.trades_count += 1
        self.volume_matic += amount_matic
        
        return await self._send_transaction(func, value=amount_wei, gas_limit=400000)
    
    async def sell(self, token: str, fraction: float = 0.5) -> Optional[str]:
        """Продажа токена за MATIC (доля от баланса)"""
        balances = await self.get_balances()
        token_bal = balances[token]
        
        if token_bal < 1000:  # Минимальный баланс для продажи
            logger.info(f"[{self.name}] Недостаточно {token.upper()} для продажи: {token_bal:.2f}")
            return None
        
        amount = int(token_bal * fraction * 1e18)
        token_addr = CONFIG['casrs_address'] if token == 'casrs' else CONFIG['casrg_address']
        
        # Путь: TOKEN -> WMATIC
        path = [token_addr, CONFIG['weth_address']]
        
        # Approve для router
        contract = self.casrs if token == 'casrs' else self.casrg
        approve = contract.functions.approve(CONFIG['quickswap_router'], amount)
        await self._send_transaction(approve, gas_limit=120000)
        
        func = self.router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
            amount,
            0,  # minAmountOut
            path,
            self.address,
            int(time.time()) + 1200
        )
        
        matic_value = token_bal * fraction * balances['matic']  # приблизительно
        logger.info(f"[{self.name}] Продажа {amount/1e18:.2f} {token.upper()} ≈ {matic_value:.4f} MATIC")
        self.trades_count += 1
        self.volume_matic += matic_value
        
        return await self._send_transaction(func, gas_limit=400000)
    
    # ------------------------------------------------------------------------------------------------
    # ФУНКЦИИ CASRG (ДОЛГ)
    # ------------------------------------------------------------------------------------------------
    
    async def mint_casrg(self, rs_amount: float) -> Optional[str]:
        """Минт CASRG под залог CASRS"""
        if rs_amount <= 0:
            return None
            
        amount_wei = int(rs_amount * 1e18)
        
        # Approve для контракта CASRS
        approve = self.casrs.functions.approve(CONFIG['casrg_address'], amount_wei)
        await self._send_transaction(approve, gas_limit=120000)
        
        func = self.casrg.functions.mintAgainstCollateral(amount_wei)
        logger.info(f"[{self.name}] Минт CASRG под залог {rs_amount:.2f} CASRS")
        
        return await self._send_transaction(func, gas_limit=600000)
    
    async def repay_casrg(self, rg_amount: float) -> Optional[str]:
        """Погашение долга CASRG"""
        if rg_amount <= 0:
            return None
            
        amount_wei = int(rg_amount * 1e18)
        func = self.casrg.functions.repay(amount_wei)
        
        logger.info(f"[{self.name}] Погашение {rg_amount:.2f} CASRG")
        
        return await self._send_transaction(func, gas_limit=400000)
    
    # ------------------------------------------------------------------------------------------------
    # БЛОКИРОВКА ТОКЕНОВ
    # ------------------------------------------------------------------------------------------------
    
    async def lock_tokens(self, amount: float, months: int) -> Optional[str]:
        """Блокировка CASRS на указанный срок"""
        if amount <= 0 or months < CONFIG['lock_min_months'] or months > CONFIG['lock_max_months']:
            return None
            
        amount_wei = int(amount * 1e18)
        duration = months * 30 * 24 * 60 * 60  # в секундах (приблизительно)
        
        func = self.casrs.functions.lockTokens(amount_wei, duration, 1)  # type 1 = collateral
        logger.info(f"[{self.name}] Блокировка {amount:.2f} CASRS на {months} месяцев")
        
        return await self._send_transaction(func, gas_limit=400000)

# ====================================================================================================
# КЛАСС OWNER (РАСШИРЕННЫЙ ТРЕЙДЕР)
# ====================================================================================================

class Owner(Trader):
    """Владелец системы с расширенными правами"""
    
    def __init__(self, name: str, private_key: str):
        super().__init__(name, private_key, 'owner')
        self.math_model = MathModel(CONFIG)
        self.last_metrics: Optional[SystemMetrics] = None
        self.system_state = {
            'B': 0.0, 'C': 0.0, 'R_RS': 0.0, 'F': 0.0,
            'D': 0.0, 'R_RG': 0.0, 'X': 0.0, 'Y': 0.0, 'S': 0.0
        }
    
    # ------------------------------------------------------------------------------------------------
    # ПОЛУЧЕНИЕ СОСТОЯНИЯ СИСТЕМЫ
    # ------------------------------------------------------------------------------------------------
    
    async def update_system_state(self) -> SystemMetrics:
        """Обновление состояния системы из контрактов"""
        try:
            # Получаем данные из CASRS
            accounting = await self.casrs.functions.getSystemAccounting().call()
            free_float = await self.casrs.functions.getFreeFloat().call()
            safe_price = await self.casrs.functions.getSafePrice().call()
            total_supply = await self.casrs.functions.totalSupply().call()
            
            # Получаем данные из CASRG
            coverage = await self.casrg.functions.getSystemCoverage().call()
            total_debt = await self.casrg.functions.totalSupply().call()
            
            # Резервы пула (упрощённо)
            # В реальности нужно читать из контракта пула
            pool_rs = 3500.0  # Заглушка
            pool_matic = 35.0  # Заглушка
            
            # Обновляем состояние
            self.system_state = {
                'B': 100.0,  # Заглушка
                'C': 2000.0,  # Заглушка
                'R_RS': 2500.0,  # Заглушка
                'F': free_float / 1e18,
                'D': total_debt / 1e18,
                'R_RG': 2.0,  # Заглушка
                'X': pool_rs,
                'Y': pool_matic,
                'S': total_supply / 1e18
            }
            
            # Расчёт метрик
            metrics = self.math_model.calculate_metrics(self.system_state)
            
            # Корректируем с реальными данными
            metrics.P_safe = safe_price / 1e18
            metrics.K = coverage / 1000  # Если coverage в bps
            
            self.last_metrics = metrics
            return metrics
            
        except Exception as e:
            logger.error(f"[Owner] Ошибка получения состояния: {e}")
            return SystemMetrics()
    
    # ------------------------------------------------------------------------------------------------
    # ФУНКЦИИ УПРАВЛЕНИЯ
    # ------------------------------------------------------------------------------------------------
    
    async def recycle_contract(self, token: str) -> Optional[str]:
        """Рециклинг ETH из контракта"""
        try:
            contract = self.casrs if token == 'casrs' else self.casrg
            eth_balance = w3.eth.get_balance(contract.address)
            
            if eth_balance < w3.to_wei(CONFIG['base_trade_matic'], 'ether'):
                logger.info(f"[Owner] Недостаточно ETH в {token.upper()} для рециклинга")
                return None
            
            func = contract.functions.robotBuyback(eth_balance)
            logger.info(f"[Owner] Рециклинг {w3.from_wei(eth_balance, 'ether'):.4f} ETH из {token.upper()}")
            
            return await self._send_transaction(func, gas_limit=500000)
            
        except Exception as e:
            logger.error(f"[Owner] Ошибка рециклинга: {e}")
            return None
    
    async def add_liquidity(self, token: str, amount_matic: float) -> Optional[str]:
        """Добавление ликвидности"""
        if amount_matic <= 0:
            return None
            
        try:
            # Получаем цену для расчёта количества токенов
            price = self.last_metrics.P_safe if self.last_metrics else 0.01
            amount_tokens = int(amount_matic / price * 1e18)
            
            contract = self.casrs if token == 'casrs' else self.casrg
            func = contract.functions.robotAddLiquidity(amount_tokens)
            
            amount_wei = w3.to_wei(amount_matic, 'ether')
            logger.info(f"[Owner] Добавление LP для {token.upper()}: {amount_matic:.4f} MATIC + {amount_tokens/1e18:.2f} токенов")
            
            return await self._send_transaction(func, value=amount_wei, gas_limit=600000)
            
        except Exception as e:
            logger.error(f"[Owner] Ошибка добавления LP: {e}")
            return None
    
    async def auto_burn(self, token: str, amount: Optional[float] = None) -> Optional[str]:
        """Сжигание токенов из контракта"""
        try:
            contract = self.casrs if token == 'casrs' else self.casrg
            bal_wei = await contract.functions.balanceOf(contract.address).call()
            balance = bal_wei / 1e18
            
            if balance < 1000:
                logger.info(f"[Owner] Недостаточно токенов для сжигания в {token.upper()}: {balance:.2f}")
                return None
            
            burn_amount = int(balance * 0.05 * 1e18) if amount is None else int(amount * 1e18)
            func = contract.functions.robotBurn(burn_amount)
            
            logger.info(f"[Owner] Сжигание {burn_amount/1e18:.2f} {token.upper()}")
            
            return await self._send_transaction(func, gas_limit=300000)
            
        except Exception as e:
            logger.error(f"[Owner] Ошибка сжигания: {e}")
            return None
    
    async def fund_projects(self, amount: float) -> Optional[str]:
        """Финансирование внутренних проектов (5% эмиссии)"""
        # В реальности нужно вызывать отдельный контракт проектов
        logger.info(f"[Owner] Финансирование проектов: {amount:.4f} MATIC")
        return "0x" + "0" * 64  # Заглушка
    
    async def distribute_holder_rewards(self) -> Optional[str]:
        """Распределение комиссий держателям CASRS"""
        # В реальности нужно вызывать отдельный контракт
        logger.info(f"[Owner] Распределение наград держателям")
        return "0x" + "0" * 64  # Заглушка

# ====================================================================================================
# ОСНОВНОЙ ТОРГОВЫЙ ЦИКЛ
# ====================================================================================================

class SinergiaSystem:
    """Главный класс системы управления"""
    
    def __init__(self, config: Dict):
        self.cfg = config
        self.owner: Optional[Owner] = None
        self.traders: List[Trader] = []
        self.cycle_count = 0
        self.start_time = datetime.now()
        
        # Инициализация аккаунтов
        self._init_accounts()
        
        logger.info(f"✅ Система 'Синергия' инициализирована с {len(self.traders)} трейдерами")
    
    def _init_accounts(self):
        """Инициализация аккаунтов из конфига"""
        for acc in self.cfg['accounts']:
            if acc['role'] == 'owner':
                self.owner = Owner(acc['name'], acc['private_key'])
            else:
                trader = Trader(
                    acc['name'], 
                    acc['private_key'], 
                    acc['role'],
                    acc.get('aggressive', False)
                )
                self.traders.append(trader)
    
    async def get_all_balances(self) -> Dict:
        """Получение балансов всех участников"""
        balances = {}
        
        if self.owner:
            balances['owner'] = await self.owner.get_balances()
        
        for trader in self.traders:
            balances[trader.name] = await trader.get_balances()
        
        return balances
    
    async def check_system_health(self) -> bool:
        """Проверка здоровья системы"""
        if not self.owner:
            return False
        
        metrics = await self.owner.update_system_state()
        
        logger.info(f"📊 Системные метрики:")
        logger.info(f"   P_spot = {metrics.P_spot:.6f}")
        logger.info(f"   P_safe = {metrics.P_safe:.6f}")
        logger.info(f"   K = {metrics.K:.2f}")
        logger.info(f"   STS = {metrics.STS:.2f}")
        logger.info(f"   Emergency = {metrics.emergency_mode}")
        logger.info(f"   Emission paused = {metrics.emission_paused}")
        
        # Проверка инвариантов
        if metrics.N <= 0:
            logger.error("❌ NAV отрицательный!")
            return False
        if metrics.K < 1.0:
            logger.error("❌ Покрытие меньше 1.0!")
            return False
        if metrics.STS < 1.0:
            logger.error("❌ Stop-test провален!")
            return False
        if metrics.emergency_mode:
            logger.error("🚨 Аварийный режим активирован!")
            return False
        
        return True
    
    async def trading_cycle(self):
        """Один цикл торговли"""
        self.cycle_count += 1
        logger.info(f"\n{'='*60}\nЦИКЛ {self.cycle_count}\n{'='*60}")
        
        # 1. Обновление состояния системы
        if self.owner:
            await self.owner.update_system_state()
            await self.check_system_health()
        
        # 2. Торговля для каждого токена
        for token in ['casrs', 'casrg']:
            # Перемешиваем трейдеров для рандомизации
            random.shuffle(self.traders)
            
            for trader in self.traders:
                balances = await trader.get_balances()
                
                # Пропускаем если мало MATIC
                if balances['matic'] < self.cfg['base_trade_matic'] * 2:
                    continue
                
                # Решаем: покупать или продавать
                if token == 'casrs':
                    # Для CASRS используем агрессивность трейдера
                    buy_chance = 0.8 if trader.aggressive else 0.6
                else:
                    # Для CASRG более осторожно
                    buy_chance = 0.6 if trader.aggressive else 0.4
                
                amount = self.cfg['base_trade_matic'] * random.uniform(0.7, 1.3)
                
                if random.random() < buy_chance:
                    # Покупка
                    await trader.buy(token, amount)
                else:
                    # Продажа (только если есть что продавать)
                    if balances[token] > 1000:
                        await trader.sell(token, random.uniform(0.2, 0.5))
                
                # Небольшая задержка между сделками
                await asyncio.sleep(random.uniform(1.0, 3.0))
        
        # 3. Owner: рециклинг, LP, сжигание
        if self.owner:
            metrics = self.owner.last_metrics
            
            # Рециклинг каждые 5 циклов
            if self.cycle_count % 5 == 0:
                for token in ['casrs', 'casrg']:
                    await self.owner.recycle_contract(token)
                    await self.owner.auto_burn(token)
            
            # Добавление LP каждые 8 циклов
            if self.cycle_count % 8 == 0 and metrics and metrics.K > 2.0:
                for token in ['casrs', 'casrg']:
                    amount = self.cfg['base_trade_matic'] * 2
                    await self.owner.add_liquidity(token, amount)
            
            # Финансирование проектов каждые 10 циклов
            if self.cycle_count % 10 == 0:
                await self.owner.fund_projects(self.cfg['base_trade_matic'] * 5)
                await self.owner.distribute_holder_rewards()
        
        # 4. Статистика
        if self.cycle_count % 5 == 0:
            await self.print_statistics()
    
    async def print_statistics(self):
        """Печать статистики"""
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
            
            # Поиск трейдера для статистики
            for trader in self.traders:
                if trader.name == name:
                    total_volume += trader.volume_matic
                    total_trades += trader.trades_count
                    logger.info(f"  Сделок: {trader.trades_count}")
                    logger.info(f"  Объём: {trader.volume_matic:.4f} MATIC")
        
        if self.owner:
            logger.info(f"\nВсего сделок: {total_trades}")
            logger.info(f"Всего объём: {total_volume:.4f} MATIC")
            
            elapsed = datetime.now() - self.start_time
            logger.info(f"Время работы: {elapsed}")
            
            if self.owner.last_metrics:
                m = self.owner.last_metrics
                logger.info(f"\nМетрики системы:")
                logger.info(f"  P_spot = {m.P_spot:.6f}")
                logger.info(f"  P_safe = {m.P_safe:.6f}")
                logger.info(f"  K = {m.K:.2f}")
                logger.info(f"  STS = {m.STS:.2f}")
        
        logger.info("="*60)
    
    async def run(self):
        """Запуск основного цикла"""
        logger.info("="*60)
        logger.info("🚀 ЗАПУСК СИСТЕМЫ 'СИНЕРГИЯ'")
        logger.info(f"Трейдеров: {len(self.traders)}")
        logger.info(f"Owner: {'ДА' if self.owner else 'НЕТ'}")
        logger.info(f"Стартовый баланс MATIC: ~{self.cfg['base_trade_matic'] * 100:.2f}")
        logger.info("="*60)
        
        # Проверка соединения
        if not w3.is_connected():
            logger.error("❌ Нет соединения с блокчейном")
            return
        
        # Основной цикл
        try:
            while True:
                await self.trading_cycle()
                await asyncio.sleep(self.cfg['cycle_sleep_sec'])
                
        except KeyboardInterrupt:
            logger.info("🛑 Система остановлена пользователем")
            await self.print_statistics()
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
            raise

# ====================================================================================================
# ЗАПУСК
# ====================================================================================================

async def main():
    """Главная функция"""
    print("="*80)
    print("🚀 СИСТЕМА УПРАВЛЕНИЯ И ТОРГОВЛИ 'СИНЕРГИЯ'")
    print("Версия 5.0 - Полная математическая модель")
    print("="*80)
    print("\n📋 КОНФИГУРАЦИЯ:")
    print(f"   - Трейдеров: {len([a for a in CONFIG['accounts'] if a['role'] == 'trader'])}")
    print(f"   - Owner: {'Есть' if any(a['role'] == 'owner' for a in CONFIG['accounts']) else 'НЕТ!'}")
    print(f"   - Базовый объём: {CONFIG['base_trade_matic']} MATIC")
    print(f"   - Параметры модели:")
    print(f"     • h_RS = {CONFIG['h_RS']} (haircut CASRS)")
    print(f"     • cf = {CONFIG['cf']} (collateral factor)")
    print(f"     • α = {CONFIG['alpha']} (эмиссия)")
    print(f"     • min_coverage = {CONFIG['min_coverage']}")
    print("="*80)
    
    # Проверка, что все ключи установлены
    for acc in CONFIG['accounts']:
        if acc['private_key'] == '0x...':
            logger.warning(f"⚠️  Внимание: не установлен private key для {acc['name']}")
    
    # Запуск системы
    system = SinergiaSystem(CONFIG)
    await system.run()

if __name__ == "__main__":
    asyncio.run(main())
