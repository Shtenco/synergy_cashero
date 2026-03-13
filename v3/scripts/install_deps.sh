#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required" >&2
  exit 1
fi

echo "[1/3] installing npm dependencies"
npm install

echo "[2/3] copying .env.example -> .env if absent"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env (edit values before deploy)"
fi

echo "[3/3] hardhat compile"
npx hardhat compile

echo "Done. Use: npm run deploy:polygon"
