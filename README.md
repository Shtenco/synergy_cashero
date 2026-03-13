# cashero

## TOP cyclic robot model (simulation)

Добавлены:

- `top_cyclic_robot.py` — симулятор циклического робота на 3 кошелька:
  - поочерёдная покупка,
  - поочерёдная частичная фиксация прибыли,
  - обязательное добавление ликвидности в оба токена,
  - адаптивная эмиссия и сжигание.
- `MODEL_TOP_CYCLIC_ROBOT.md` — математическая постановка и формулы.

Запуск:

```bash
python top_cyclic_robot.py
```

## Real multi-RPC robot (live trading)

- `real_polygon_cyclic_robot.py` — реальный робот для Polygon c:
  - ротацией нескольких RPC (`RPC_POLYGON_LIST`),
  - поочерёдными действиями с 3 кошельков (`owner.env`, `bot1.env`, `bot2.env`),
  - рандомными задержками между кошельками,
  - поочерёдной покупкой и частичной фиксацией,
  - обязательным LP-реинвестом в пару `CASRS/WMATIC` через `addLiquidityETH`.

Пример запуска:

```bash
export RPC_POLYGON_LIST="https://polygon-rpc.com,https://polygon-bor-rpc.publicnode.com,https://rpc.ankr.com/polygon"
export REAL_BUY_MATIC=0.03
export REAL_TAKE_PROFIT=0.20
export REAL_LP_INVEST_MATIC=0.05
export MIN_WALLET_DELAY_SEC=2
export MAX_WALLET_DELAY_SEC=8
python real_polygon_cyclic_robot.py
```

⚠️ Скрипт отправляет реальные транзакции. Сначала запускайте на минимальных объёмах.


## Exact simulation of current bot logic (150 cycles)

Для симуляции **именно текущей логики** `sinergia_bot.py` (правила `strategy_step`) без RPC:

```bash
python simulate_our_robot_150.py
```

Скрипт сохраняет:
- `our_robot_exact_150_report.md`
- `our_robot_exact_150_report.json`
