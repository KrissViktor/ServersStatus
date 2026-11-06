#!/bin/bash
# Run via sudo. Credentials are read from the protected local environment file.
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then
    echo 'Run this helper with sudo.' >&2
    exit 1
fi
case "${1:-}" in
    --discover-chat|--test|--daily-test) ;;
    *) echo 'Usage: sudo bash deploy/telegram-command.sh --discover-chat|--test|--daily-test' >&2; exit 1 ;;
esac
set -a
source /etc/serversstatus-telegram.env
set +a
export STATUS_DB="${STATUS_DB:-/var/lib/serversstatus/status.sqlite3}"
cd "$(dirname "$0")/.."
exec .venv/bin/python -m server.notifications "$1"
