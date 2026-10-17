#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d "node_modules/electron" ]; then
  echo "正在安裝 Electron 桌面執行環境..."
  npm install
fi

exec npx electron .
