# CAShero v3 contracts + bot (по двухконтурной модели)

Созданы новые контракты:
- `contracts/CASRSv3.sol`
- `contracts/CASRGv3.sol`

Создан отдельный бот под них:
- `cashero_v3_bot.py`

## Что реализовано

### CASRSv3
- ERC20 токен с ролями owner/bot.
- Метрики двухконтурной модели: `pSpot`, `pTwap`, `pSafe`.
- Функция `getSystemAccounting()` (assets/liabilities/nav/coverage).
- Эмиссия по росту `mintByGrowth()` с распределением:
  - 5% проекты,
  - 70% резерв,
  - 20% free-float,
  - 10% founder vesting.
- Сжигание по падению `burnByDecline()`.
- Механики дополнения `η, δ, ψ`:
  - `accrueTradingFee()`,
  - `robotSellReserveAndAddLiquidity()`.

### CASRGv3
- ERC20 долговой токен.
- Кредитование под залог CASRS:
  - `mintAgainstCollateral()`.
- Погашение и возврат залога:
  - `repay()`.
- Ликвидация:
  - `liquidate()`.

### Bot v3
- 3 кошелька по очереди (owner/bot1/bot2):
  - покупка CASRS,
  - частичная фиксация.
- Вызовы контурных функций v3:
  - `updateState`,
  - `mintByGrowth`,
  - `robotSellReserveAndAddLiquidity`,
  - `mintAgainstCollateral` (опционально).

## Важно

- Нельзя гарантировать «сделать богатым» — это рискованная рыночная среда.
- Перед mainnet обязательно прогонять через testnet + аудит + ограничения рисков.
