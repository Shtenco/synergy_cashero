# CAShero v3 setup

Эта папка содержит **все файлы для v3**:
- `contracts/CASRSv3.sol`
- `contracts/CASRGv3.sol`
- `cashero_v3_bot.py`
- Hardhat-конфиг + скрипты install/deploy/liquidity.

## 1) Установка зависимостей (Hardhat)

```bash
cd v3
./scripts/install_deps.sh
```

## 2) Настройка окружения

```bash
cp .env.example .env
# заполнить OWNER_PRIVATE_KEY, FOUNDER_VESTING, PROJECT_VAULT
```

## 3) Деплой v3-контрактов

```bash
npm run deploy:polygon
```

После деплоя адреса сохраняются в `v3-deploy-addresses.json`.

## 4) Добавление ликвидности по 10 POL в каждый пул

Скрипт добавляет:
- 10 POL в пул `CASRSv3/WMATIC`,
- 10 POL в пул `CASRGv3/WMATIC`.

```bash
# в .env должны быть CASRSV3_ADDRESS и CASRGV3_ADDRESS
npm run liquidity:10pol
```

## 5) Бот v3

```bash
python cashero_v3_bot.py
```

> Перед mainnet обязательно тестируйте на Amoy и малых суммах.
