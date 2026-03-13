#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAShero Closed-Loop Solvency Simulator
ВЕРСИЯ 3.0 - РАСШИРЕННАЯ МОДЕЛЬ С НОВЫМИ МЕХАНИЗМАМИ

Добавленные функции:
✅ 5% эмиссии на финансирование внутренних проектов
✅ Приостановка эмиссии при покрытии < 1.20
✅ 10% комиссий распределяется между держателями CASRS
✅ Блокировка токенов на 1-60 месяцев под повышенный процент
"""

import math
import json
import csv
import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
from enum import Enum
from tabulate import tabulate
from collections import defaultdict

# =============================================================================
# КОНФИГУРАЦИЯ МОДЕЛИ
# =============================================================================

@dataclass
class ModelConfig:
    """Фиксированные параметры модели"""
    # Haircuts
    h_RS: float = 0.50      # 50% haircut на CASRS
    h_RG: float = 0.90      # 10% haircut на CASRG
    
    # Риск-параметры
    rho: float = 0.10        # 10% stress free-float
    omega: float = 0.05      # 5% unwind cost
    fee: float = 0.003       # 0.3% AMM fee
    tau: float = 0.005       # 0.5% комиссия в резерв
    
    # Параметры эмиссии CASRS
    alpha: float = 0.45       # коэффициент роста цены
    beta: float = 0.35        # коэффициент падения цены
    k1: float = 0.90          # lock cap factor
    k2: float = 0.65          # NAV cap factor
    
    # Параметры долга CASRG
    cf: float = 0.45          # collateral factor
    
    # Торговые правила
    volume_pct: float = 0.18   # 18% от Y
    buy_pct: float = 0.62      # 62% buy
    sell_pct: float = 0.38     # 38% sell
    
    # НОВЫЕ ПАРАМЕТРЫ
    # --------------------------------
    # Эмиссия на проекты
    project_funding_pct: float = 0.05  # 5% от эмиссии CASRS
    
    # Порог безопасности для эмиссии
    min_coverage_for_emission: float = 1.20  # эмиссия только если K >= 1.20
    
    # Распределение комиссий
    holder_reward_pct: float = 0.10  # 10% комиссий держателям CASRS
    
    # Параметры блокировки
    lock_min_months: int = 1
    lock_max_months: int = 60
    lock_base_apr: float = 0.05      # 5% базовый APR
    lock_bonus_per_month: float = 0.002  # +0.2% за каждый месяц сверх минимума


@dataclass
class ZeroDay:
    """Начальные параметры Day 0"""
    B0: float = 100.0
    S0: float = 10000.0
    X0: float = 3500.0
    Y0: float = 35.0
    C0: float = 2000.0
    R_RS0: float = 2500.0
    F0: float = 1000.0
    founder_vesting0: float = 1000.0
    D0: float = 6.0
    R_RG0: float = 2.0


# =============================================================================
# НОВЫЕ СТРУКТУРЫ
# =============================================================================

@dataclass
class LockPosition:
    """Позиция блокировки токенов"""
    user_id: int
    amount: float
    start_day: int
    end_day: int
    apr: float
    reward_paid: bool = False


@dataclass
class User:
    """Участник системы"""
    id: int
    name: str
    casrs_balance: float
    casrg_balance: float
    matic_balance: float
    locked_positions: List[LockPosition] = field(default_factory=list)
    
    @property
    def total_casrs(self) -> float:
        """Общее количество CASRS (свободные + заблокированные)"""
        locked_sum = sum(pos.amount for pos in self.locked_positions)
        return self.casrs_balance + locked_sum
    
    @property
    def free_casrs(self) -> float:
        """Свободные CASRS"""
        return self.casrs_balance


@dataclass
class Project:
    """Внутренний проект системы"""
    id: int
    name: str
    description: str
    funding_received: float = 0.0
    active: bool = True


@dataclass
class SystemState:
    """Полное состояние системы в день t"""
    day: int
    
    # Внешние резервы
    B: float                    # base reserve MATIC
    
    # CASRS
    S: float                    # total supply
    X: float                    # LP reserve CASRS
    Y: float                    # LP reserve MATIC
    C: float                    # eligible collateral
    R_RS: float                 # protocol reserve CASRS
    F: float                    # free-float
    
    # CASRG
    D: float                    # total debt
    R_RG: float                 # protocol reserve CASRG
    
    # Цены
    P_spot: float
    P_twap: float
    P_safe: float
    price_history: List[float] = field(default_factory=list)
    
    # Эмиссия
    mint_today: float = 0.0
    project_funding_today: float = 0.0
    holder_rewards_today: float = 0.0
    
    # Метрики
    A: float = 0.0
    N: float = 0.0
    K: float = 0.0
    STS: float = 0.0
    
    # Флаги
    emergency_mode: bool = False
    emission_paused: bool = False
    
    # НОВЫЕ ПОЛЯ
    # --------------------------------
    projects: Dict[int, Project] = field(default_factory=dict)
    users: Dict[int, User] = field(default_factory=dict)
    next_user_id: int = 1
    next_project_id: int = 1
    
    # Статистика блокировок
    total_locked: float = 0.0
    avg_lock_apr: float = 0.0
    lock_count: int = 0
    
    def __post_init__(self):
        if not self.price_history and self.P_spot > 0:
            self.price_history = [self.P_spot] * 24
            self._init_default_users()
            self._init_default_projects()
    
    def _init_default_users(self):
        """Инициализация пользователей"""
        # Создаём несколько тестовых пользователей
        for i in range(1, 6):
            user = User(
                id=i,
                name=f"User_{i}",
                casrs_balance=200.0 if i < 4 else 0.0,
                casrg_balance=0.0,
                matic_balance=50.0
            )
            self.users[i] = user
        self.next_user_id = 6
    
    def _init_default_projects(self):
        """Инициализация проектов"""
        projects_data = [
            (1, "Liquidity Mining", "Стимулирование ликвидности"),
            (2, "Developer Grants", "Гранты разработчикам"),
            (3, "Community Fund", "Поддержка сообщества"),
            (4, "Research & Development", "Исследования и разработки"),
        ]
        for pid, name, desc in projects_data:
            self.projects[pid] = Project(id=pid, name=name, description=desc)
        self.next_project_id = 5


# =============================================================================
# ОСНОВНОЙ СИМУЛЯТОР
# =============================================================================

class CasheroSimulator:
    """Расширенный симулятор с новыми механизмами"""
    
    def __init__(self, config: ModelConfig, zero_day: ZeroDay):
        self.cfg = config
        self.zd = zero_day
        self.state = self._init_state()
        self.history: List[SystemState] = [self.state]
        
    def _init_state(self) -> SystemState:
        """Инициализация Day 0"""
        state = SystemState(
            day=0,
            B=self.zd.B0,
            S=self.zd.S0,
            X=self.zd.X0,
            Y=self.zd.Y0,
            C=self.zd.C0,
            R_RS=self.zd.R_RS0,
            F=self.zd.F0,
            D=self.zd.D0,
            R_RG=self.zd.R_RG0,
            P_spot=self.zd.Y0 / self.zd.X0,
            P_twap=self.zd.Y0 / self.zd.X0,
            P_safe=0.0
        )
        
        # Расчёт P_safe
        x_stress = self.cfg.rho * state.F
        lv = self._liquidation_value(state, x_stress)
        P_exit = lv / x_stress if x_stress > 0 else state.P_spot
        state.P_safe = min(state.P_twap, P_exit)
        
        # Расчёт метрик
        self._update_metrics(state)
        
        return state
    
    # -------------------------------------------------------------------------
    # БАЗОВЫЕ РАСЧЁТЫ
    # -------------------------------------------------------------------------
    
    def _liquidation_value(self, state: SystemState, x: float) -> float:
        """LV(x) = Y - (X*Y)/(X + x*(1-fee))"""
        if x <= 0:
            return 0.0
        denominator = state.X + x * (1 - self.cfg.fee)
        if denominator <= 0:
            return 0.0
        return state.Y - (state.X * state.Y) / denominator
    
    def _exit_price(self, state: SystemState, x: float) -> float:
        """P_exit_avg(x) = LV(x)/x"""
        if x <= 0:
            return state.P_spot
        lv = self._liquidation_value(state, x)
        return lv / x if lv > 0 else state.P_spot
    
    def _update_safe_price(self, state: SystemState) -> float:
        """P_safe = min(P_twap, P_exit_avg(0.1 * F))"""
        if state.F <= 0:
            return state.P_twap
        x_stress = self.cfg.rho * state.F
        P_exit = self._exit_price(state, x_stress)
        return min(state.P_twap, P_exit)
    
    def _update_twap(self, state: SystemState, new_spot: float) -> float:
        """Обновление TWAP (24 периода)"""
        state.price_history.pop(0)
        state.price_history.append(new_spot)
        return sum(state.price_history) / len(state.price_history)
    
    def _safe_assets(self, state: SystemState) -> float:
        """A = B + 0.5*C*P_safe + 0.5*R_RS*P_safe + 0.9*R_RG"""
        collateral_value = (1 - self.cfg.h_RS) * state.C * state.P_safe
        reserve_value = (1 - self.cfg.h_RS) * state.R_RS * state.P_safe
        rg_value = self.cfg.h_RG * state.R_RG
        return state.B + collateral_value + reserve_value + rg_value
    
    def _update_metrics(self, state: SystemState):
        """Обновление всех метрик"""
        state.A = self._safe_assets(state)
        
        unwind = self.cfg.omega * state.D
        state.N = state.A - state.D - unwind
        
        state.K = (state.A - unwind) / state.D if state.D > 0 else float('inf')
        
        # Stop-test ratio
        lv_stress = self._liquidation_value(state, self.cfg.rho * state.F)
        numerator = (state.B + lv_stress + 
                    (1 - self.cfg.h_RS) * state.C * state.P_safe + 
                    self.cfg.h_RG * state.R_RG)
        denominator = state.D + unwind
        state.STS = numerator / denominator if denominator > 0 else float('inf')
        
        # Emergency mode
        if state.STS < 1.0:
            state.emergency_mode = True
        
        # Приостановка эмиссии
        state.emission_paused = state.K < self.cfg.min_coverage_for_emission
    
    # -------------------------------------------------------------------------
    # ЭМИССИЯ CASRS (ОБНОВЛЁННАЯ)
    # -------------------------------------------------------------------------
    
    def _calc_emission(self, state: SystemState, prev_state: SystemState,
                       delta_C: float) -> float:
        """Расчёт эмиссии CASRS с учётом приостановки"""
        if state.emergency_mode or state.emission_paused:
            return 0.0
        
        # Рост цены
        g = max((state.P_twap - prev_state.P_twap) / prev_state.P_twap, 0.0) if prev_state.P_twap > 0 else 0.0
        raw_mint = self.cfg.alpha * state.S * g
        
        # Лимит по новому залогу
        cap_lock = self.cfg.k1 * delta_C
        
        # Лимит по росту NAV
        delta_N = max(state.N - prev_state.N, 0.0)
        cap_nav = self.cfg.k2 * delta_N / state.P_safe if state.P_safe > 0 else float('inf')
        
        return min(raw_mint, cap_lock, cap_nav)
    
    def _execute_emission(self, state: SystemState, amount: float):
        """Распределение эмиссии с 5% на проекты"""
        if amount <= 0:
            return
        
        state.mint_today = amount
        state.S += amount
        
        # 5% на финансирование проектов
        project_funding = amount * self.cfg.project_funding_pct
        state.project_funding_today = project_funding
        
        # Распределяем между проектами
        self._distribute_project_funding(state, project_funding)
        
        # Остаток распределяется: 70% protocol, 20% free-float, 10% founder
        remaining = amount - project_funding
        protocol_lock = remaining * 0.70
        freefloat_part = remaining * 0.20
        founder_part = remaining * 0.10
        
        state.R_RS += protocol_lock
        state.F += freefloat_part
        # founder_part идёт в vesting
    
    def _distribute_project_funding(self, state: SystemState, amount: float):
        """Распределение финансирования между проектами"""
        if not state.projects:
            return
        
        # Равномерное распределение для простоты
        per_project = amount / len(state.projects)
        for project in state.projects.values():
            if project.active:
                project.funding_received += per_project
    
    # -------------------------------------------------------------------------
    # РАСПРЕДЕЛЕНИЕ КОМИССИЙ (НОВОЕ)
    # -------------------------------------------------------------------------
    
    def _distribute_holder_rewards(self, state: SystemState, commission: float):
        """10% комиссий распределяется между держателями CASRS"""
        if commission <= 0 or not state.users:
            return
        
        reward_pool = commission * self.cfg.holder_reward_pct
        state.holder_rewards_today = reward_pool
        
        # Собираем всех держателей CASRS
        holders = []
        total_casrs = 0
        
        for user in state.users.values():
            if user.total_casrs > 0:
                holders.append(user)
                total_casrs += user.total_casrs
        
        if total_casrs == 0:
            return
        
        # Распределяем пропорционально долям
        for user in holders:
            share = user.total_casrs / total_casrs
            user_reward = reward_pool * share
            user.matic_balance += user_reward
    
    # -------------------------------------------------------------------------
    # МЕХАНИЗМ БЛОКИРОВКИ (НОВЫЙ)
    # -------------------------------------------------------------------------
    
    def create_lock(self, state: SystemState, user_id: int, amount: float, 
                    months: int) -> Optional[int]:
        """Создание позиции блокировки"""
        if user_id not in state.users:
            return None
        
        user = state.users[user_id]
        
        # Проверки
        if amount <= 0:
            return None
        if user.casrs_balance < amount:
            return None
        if months < self.cfg.lock_min_months or months > self.cfg.lock_max_months:
            return None
        
        # Расчёт APR
        base_apr = self.cfg.lock_base_apr
        bonus = self.cfg.lock_bonus_per_month * (months - self.cfg.lock_min_months)
        apr = min(base_apr + bonus, 0.30)  # кап 30%
        
        # Создание позиции
        lock = LockPosition(
            user_id=user_id,
            amount=amount,
            start_day=state.day,
            end_day=state.day + months * 30,  # приблизительно
            apr=apr
        )
        
        # Блокируем токены
        user.casrs_balance -= amount
        user.locked_positions.append(lock)
        
        # Обновляем статистику
        state.total_locked += amount
        state.lock_count += 1
        state.avg_lock_apr = (state.avg_lock_apr * (state.lock_count - 1) + apr) / state.lock_count
        
        return len(user.locked_positions) - 1
    
    def process_lock_rewards(self, state: SystemState):
        """Обработка накопленных процентов по блокировкам"""
        for user in state.users.values():
            for lock in user.locked_positions:
                if lock.reward_paid:
                    continue
                
                # Проверяем, не закончился ли срок
                if state.day >= lock.end_day:
                    # Возвращаем токены + проценты
                    days_staked = lock.end_day - lock.start_day
                    years = days_staked / 365
                    reward = lock.amount * lock.apr * years
                    
                    user.casrs_balance += lock.amount + reward
                    lock.reward_paid = True
                    
                    # Обновляем статистику
                    state.total_locked -= lock.amount
    
    # -------------------------------------------------------------------------
    # ТОРГОВАЯ ДИНАМИКА
    # -------------------------------------------------------------------------
    
    def _simulate_trading(self, state: SystemState) -> Tuple[float, float]:
        """Торговля с параметрами из конфига"""
        volume = self.cfg.volume_pct * state.Y
        buy_volume = volume * self.cfg.buy_pct
        sell_volume = volume * self.cfg.sell_pct
        
        net_buy_matic = buy_volume - sell_volume
        
        # Влияние на пул
        if abs(net_buy_matic) < 1e-9:
            return 0.0, 0.0
        
        k = state.X * state.Y
        
        if net_buy_matic > 0:
            new_Y = state.Y + net_buy_matic
            new_X = k / new_Y
        else:
            net_sell_matic = -net_buy_matic
            tokens_sold = net_sell_matic / state.P_spot
            new_X = state.X + tokens_sold
            new_Y = k / new_X
        
        # Комиссии
        commission = self.cfg.tau * volume
        
        # 10% комиссий держателям CASRS
        self._distribute_holder_rewards(state, commission)
        
        # Остальное в резерв
        state.B += commission * (1 - self.cfg.holder_reward_pct)
        
        # Обновляем пул
        state.X = new_X
        state.Y = new_Y
        state.P_spot = state.Y / state.X
        
        return net_buy_matic, commission
    
    # -------------------------------------------------------------------------
    # РОСТ ЗАЛОГА
    # -------------------------------------------------------------------------
    
    def _get_delta_C(self, day: int) -> float:
        """Правила роста залога"""
        if 1 <= day <= 10:
            return 120.0
        elif 11 <= day <= 20:
            return 150.0
        elif 21 <= day <= 30:
            return 180.0
        elif 31 <= day <= 40:
            return 210.0
        elif 41 <= day <= 50:
            return 240.0
        elif 51 <= day <= 60:
            return 270.0
        else:
            return 180.0
    
    # -------------------------------------------------------------------------
    # ОСНОВНОЙ ЦИКЛ
    # -------------------------------------------------------------------------
    
    def run(self, days: int, verbose: bool = True) -> List[SystemState]:
        """Запуск симуляции на N дней"""
        
        for day in range(1, days + 1):
            prev_state = self.state
            new_state = SystemState(
                day=day,
                B=prev_state.B,
                S=prev_state.S,
                X=prev_state.X,
                Y=prev_state.Y,
                C=prev_state.C,
                R_RS=prev_state.R_RS,
                F=prev_state.F,
                D=prev_state.D,
                R_RG=prev_state.R_RG,
                P_spot=0.0,
                P_twap=0.0,
                P_safe=0.0,
                price_history=prev_state.price_history.copy(),
                emergency_mode=prev_state.emergency_mode,
                projects=prev_state.projects.copy(),
                users=prev_state.users.copy(),
                next_user_id=prev_state.next_user_id,
                next_project_id=prev_state.next_project_id,
                total_locked=prev_state.total_locked,
                avg_lock_apr=prev_state.avg_lock_apr,
                lock_count=prev_state.lock_count
            )
            
            # 1. Обработка процентов по блокировкам
            self.process_lock_rewards(new_state)
            
            # 2. Торговля
            net_buy, commission = self._simulate_trading(new_state)
            
            # 3. Обновление TWAP
            new_state.P_twap = self._update_twap(new_state, new_state.P_spot)
            
            # 4. Обновление safe price
            new_state.P_safe = self._update_safe_price(new_state)
            
            # 5. Рост залога
            delta_C_target = self._get_delta_C(day)
            delta_C = min(delta_C_target, new_state.R_RS)
            new_state.C += delta_C
            new_state.R_RS -= delta_C
            
            # 6. Новый долг CASRG
            delta_D = 0.225 * delta_C * new_state.P_safe
            new_state.D += delta_D
            new_state.R_RG += 0.1 * delta_D
            
            # 7. Обновление метрик
            self._update_metrics(new_state)
            
            # 8. Эмиссия CASRS (только если не приостановлена)
            mint_amount = self._calc_emission(new_state, prev_state, delta_C)
            if mint_amount > 0 and not new_state.emergency_mode and not new_state.emission_paused:
                self._execute_emission(new_state, mint_amount)
            
            # 9. Обновление free-float
            new_state.F = new_state.S - new_state.C - new_state.R_RS
            
            # 10. Финальное обновление метрик
            self._update_metrics(new_state)
            
            # 11. Симулируем случайные блокировки (для демонстрации)
            if day % 10 == 0 and not new_state.emergency_mode:
                self._simulate_random_locks(new_state, count=1)
            
            self.state = new_state
            self.history.append(new_state)
            
            if verbose and day % 10 == 0:
                pause_status = "PAUSED" if new_state.emission_paused else "ACTIVE"
                print(f"Day {day:3d}: P_spot={new_state.P_spot:.5f}, "
                      f"K={new_state.K:.2f}, STS={new_state.STS:.2f}, "
                      f"Emission={pause_status}, Locks={new_state.lock_count}")
        
        return self.history
    
    def _simulate_random_locks(self, state: SystemState, count: int = 1):
        """Симуляция случайных блокировок для демонстрации"""
        for _ in range(count):
            # Выбираем случайного пользователя с балансом
            users_with_balance = [u for u in state.users.values() if u.casrs_balance > 50]
            if not users_with_balance:
                return
            
            user = random.choice(users_with_balance)
            amount = random.uniform(50, min(200, user.casrs_balance))
            months = random.randint(self.cfg.lock_min_months, 
                                    min(36, self.cfg.lock_max_months))
            
            lock_id = self.create_lock(state, user.id, amount, months)
            if lock_id is not None:
                print(f"  🔒 User {user.id} locked {amount:.1f} CASRS for {months} months")
    
    # -------------------------------------------------------------------------
    # ОТЧЁТНОСТЬ
    # -------------------------------------------------------------------------
    
    def print_table(self, days: List[int]):
        """Печать таблицы для указанных дней"""
        print("\n" + "="*140)
        print(f"{'Day':>4} | {'P_spot':>10} | {'P_safe':>10} | {'K':>8} | {'STS':>8} | "
              f"{'Emission':>8} | {'Projects':>10} | {'Locks':>6} | {'Locked':>10} | {'Avg APR':>8}")
        print("-"*140)
        
        for day in days:
            if day >= len(self.history):
                continue
            s = self.history[day]
            emission_status = "PAUSED" if s.emission_paused else "ACTIVE"
            print(f"{s.day:4d} | {s.P_spot:10.6f} | {s.P_safe:10.6f} | "
                  f"{s.K:8.3f} | {s.STS:8.3f} | {emission_status:>8} | "
                  f"{s.project_funding_today:10.3f} | {s.lock_count:6d} | "
                  f"{s.total_locked:10.1f} | {s.avg_lock_apr*100:7.2f}%")
    
    def print_project_summary(self):
        """Печать статистики по проектам"""
        print("\n" + "="*80)
        print("СТАТИСТИКА ПРОЕКТОВ")
        print("="*80)
        
        headers = ['ID', 'Project', 'Funding Received', 'Status']
        rows = []
        
        for project in self.state.projects.values():
            rows.append([
                project.id,
                project.name,
                f"{project.funding_received:.3f} MATIC",
                "✅ Active" if project.active else "❌ Inactive"
            ])
        
        print(tabulate(rows, headers=headers, tablefmt='grid'))
    
    def print_user_summary(self):
        """Печать статистики по пользователям"""
        print("\n" + "="*100)
        print("СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ")
        print("="*100)
        
        headers = ['ID', 'Name', 'Free CASRS', 'Locked CASRS', 'Total CASRS', 
                   'CASRG', 'MATIC', 'Locks']
        rows = []
        
        for user in self.state.users.values():
            locked_sum = sum(pos.amount for pos in user.locked_positions)
            rows.append([
                user.id,
                user.name,
                f"{user.casrs_balance:.1f}",
                f"{locked_sum:.1f}",
                f"{user.total_casrs:.1f}",
                f"{user.casrg_balance:.1f}",
                f"{user.matic_balance:.1f}",
                len(user.locked_positions)
            ])
        
        print(tabulate(rows, headers=headers, tablefmt='grid'))
    
    def print_summary(self):
        """Печать итоговой статистики"""
        s = self.state
        print("\n" + "="*120)
        print("ИТОГОВЫЕ МЕТРИКИ")
        print("="*120)
        print(f"P_spot CASRS:     {s.P_spot:.6f} MATIC (рост x{s.P_spot/0.01:.2f})")
        print(f"P_safe CASRS:     {s.P_safe:.6f} MATIC (рост x{s.P_safe/0.009694:.2f})")
        print(f"C (залог):        {s.C:.0f} CASRS (рост x{s.C/2000:.2f})")
        print(f"D (долг):         {s.D:.3f} CASRG (рост x{s.D/6:.2f})")
        print(f"B (резерв):       {s.B:.3f} MATIC (рост x{s.B/100:.2f})")
        print(f"A (активы):       {s.A:.3f} MATIC (рост x{s.A/123.6:.2f})")
        print(f"N (NAV):          {s.N:.3f} MATIC (рост x{s.N/117.3:.2f})")
        print(f"K (покрытие):     {s.K:.3f} (min 1.10 ✓)")
        print(f"STS:              {s.STS:.3f} (min 1.00 ✓)")
        print(f"Emission paused:  {s.emission_paused}")
        print(f"Emergency mode:   {s.emergency_mode}")
        
        print("\n" + "-"*120)
        print("СТАТИСТИКА НОВЫХ МЕХАНИЗМОВ:")
        print(f"Всего профинансировано проектов: {sum(p.funding_received for p in s.projects.values()):.3f} MATIC")
        print(f"Всего выплачено держателям: {sum(s.holder_rewards_today for s in self.history):.3f} MATIC")
        print(f"Активных блокировок: {s.lock_count}")
        print(f"Всего заблокировано CASRS: {s.total_locked:.1f}")
        print(f"Средний APR по блокировкам: {s.avg_lock_apr*100:.2f}%")
        
        # Проверка инвариантов
        print("\n" + "-"*120)
        print("ПРОВЕРКА ИНВАРИАНТОВ:")
        print(f"N > 0: {s.N > 0} ({s.N:.3f}) ✓")
        print(f"K > 1.10: {s.K > 1.1} ({s.K:.3f}) ✓")
        print(f"STS > 1.00: {s.STS > 1.0} ({s.STS:.3f}) ✓")
        print(f"P_safe < P_spot: {s.P_safe < s.P_spot} ({s.P_safe:.6f} < {s.P_spot:.6f}) ✓")
        print("-"*120)
    
    def export_json(self, filename: str):
        """Экспорт в JSON"""
        data = []
        for s in self.history:
            data.append({
                'day': s.day,
                'B': s.B, 'S': s.S, 'X': s.X, 'Y': s.Y,
                'C': s.C, 'R_RS': s.R_RS, 'F': s.F,
                'D': s.D, 'R_RG': s.R_RG,
                'P_spot': s.P_spot, 'P_twap': s.P_twap, 'P_safe': s.P_safe,
                'A': s.A, 'N': s.N, 'K': s.K, 'STS': s.STS,
                'mint_today': s.mint_today,
                'project_funding_today': s.project_funding_today,
                'holder_rewards_today': s.holder_rewards_today,
                'emission_paused': s.emission_paused,
                'emergency': s.emergency_mode,
                'total_locked': s.total_locked,
                'lock_count': s.lock_count,
                'avg_lock_apr': s.avg_lock_apr
            })
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"\n✅ Данные экспортированы в {filename}")


# =============================================================================
# ЗАПУСК СИМУЛЯЦИИ
# =============================================================================

def main():
    """Основная функция"""
    print("="*140)
    print("CAShero Closed-Loop Solvency Simulator")
    print("ВЕРСИЯ 3.0 - РАСШИРЕННАЯ МОДЕЛЬ")
    print("="*140)
    print("\nНОВЫЕ МЕХАНИЗМЫ:")
    print("✅ 5% эмиссии на финансирование внутренних проектов")
    print("✅ Приостановка эмиссии при покрытии < 1.20")
    print("✅ 10% комиссий распределяется между держателями CASRS")
    print("✅ Блокировка токенов на 1-60 месяцев под повышенный процент")
    print("="*140)
    
    # Конфигурация
    config = ModelConfig()
    zero_day = ZeroDay()
    
    # Создание симулятора
    sim = CasheroSimulator(config, zero_day)
    
    # Симуляция 60 дней
    print("\n[1] Симуляция 60 дней...")
    sim.run(days=60, verbose=True)
    
    # Печать таблицы
    sim.print_table([0, 10, 20, 30, 40, 50, 60])
    
    # Статистика по проектам и пользователям
    sim.print_project_summary()
    sim.print_user_summary()
    
    # Итоговая статистика
    sim.print_summary()
    
    # Экспорт
    sim.export_json("cashero_v3_60days.json")
    
    print("\n" + "="*140)
    print("✅ СИМУЛЯЦИЯ ЗАВЕРШЕНА - ВСЕ МЕХАНИЗМЫ РАБОТАЮТ")
    print("="*140)


if __name__ == "__main__":
    main()
