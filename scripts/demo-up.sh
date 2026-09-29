#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  python3 scripts/init_env.py
fi
docker compose up -d --build
if [ "${1:-}" = "--activate-workflows" ]; then
  python3 scripts/bootstrap_workflows.py import --activate-demo
fi
web_port=$(sed -n 's/^WEB_HOST_PORT=//p' .env | tail -n 1 | tr -d '\r')
n8n_port=$(sed -n 's/^N8N_HOST_PORT=//p' .env | tail -n 1 | tr -d '\r')
case "$web_port" in ''|*[!0-9]*) web_port=8080 ;; esac
case "$n8n_port" in ''|*[!0-9]*) n8n_port=5678 ;; esac
printf 'Portal: http://127.0.0.1:%s  |  n8n: http://127.0.0.1:%s\n' "$web_port" "$n8n_port"
