#!/usr/bin/env bash
# Отдельный Python 3.13 только для веб-портала. ОС, агенты и их службы не меняются.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PREPARE=0
TARGET_PYTHON=''
while (($#)); do
  case "$1" in
    --prepare-only) PREPARE=1; shift ;;
    --python) TARGET_PYTHON=${2:?Укажите путь к Python 3.13}; shift 2 ;;
    --help) echo 'Использование: bash deploy/upgrade-portal-python.sh [--prepare-only] [--python /путь/python3.13]'; exit 0 ;;
    *) echo "Неизвестный параметр: $1" >&2; exit 2 ;;
  esac
done
if [[ $ROOT =~ [[:space:]%] ]]; then echo 'Путь к порталу не должен содержать пробелы или %.' >&2; exit 2; fi
if (( ! PREPARE )) && (( EUID != 0 )); then echo 'Для переключения службы запустите скрипт через sudo.' >&2; exit 2; fi
[[ $(uname -s) == Linux ]] || { echo 'Поддерживается Linux.' >&2; exit 2; }
case $(uname -m) in aarch64|x86_64) ;; *) echo 'Нужна 64-разрядная ОС ARM64 или x86_64.' >&2; exit 2 ;; esac
exec 9>"$ROOT/.portal-runtime-upgrade.lock"
flock -n 9 || { echo 'Обновление Python уже выполняется.' >&2; exit 2; }
OLD_PYTHON="$ROOT/.venv/bin/python"
[[ -x $OLD_PYTHON ]] || { echo 'Не найдена существующая .venv портала.' >&2; exit 2; }
"$OLD_PYTHON" -c 'import shutil,sys; assert shutil.disk_usage(sys.argv[1]).free >= 600*1024**2, "Для подготовки нового Python нужно не менее 600 МБ свободного места"' "$ROOT"
UNIT=serversstatus.service
DROPIN=/etc/systemd/system/serversstatus.service.d/99-portal-python.conf
if (( ! PREPARE )); then
  [[ $(systemctl show --value --property=WorkingDirectory "$UNIT") == "$ROOT" ]] || { echo 'Рабочий каталог службы отличается от каталога проекта; переключение отменено.' >&2; exit 2; }
  systemctl is-active --quiet "$UNIT" || { echo 'Сначала восстановите работающую службу портала; автоматическое переключение отменено.' >&2; exit 2; }
fi
STAMP=$(date -u +%Y%m%dT%H%M%SZ)-$$
CANDIDATE="$ROOT/.portal-venv-313-$STAMP"
BOOTSTRAP=$(mktemp -d "${TMPDIR:-/tmp}/serversstatus-python.XXXXXXXX")
ACTIVATED=0
HAD_DROPIN=0
BACKUP="$ROOT/.portal-runtime-backups/$STAMP.conf"
cleanup() { rm -rf -- "$BOOTSTRAP"; }
rollback() {
  local code=${1:-$?}
  trap - ERR INT TERM
  set +e
  if (( ACTIVATED )); then
    echo 'Проверка нового процесса не прошла. Восстанавливаем прежний запуск портала.' >&2
    if (( HAD_DROPIN )); then cp -- "$BACKUP" "$DROPIN"; else rm -f -- "$DROPIN"; fi
    systemctl daemon-reload
    systemctl restart "$UNIT"
    systemctl is-active --quiet "$UNIT" || echo 'Не удалось подтвердить восстановление. Проверьте journalctl -u serversstatus.' >&2
  fi
  exit "${code:-1}"
}
trap cleanup EXIT
trap rollback ERR
trap 'rollback 130' INT
trap 'rollback 143' TERM
export UV_PYTHON_INSTALL_DIR="$ROOT/.portal-python"
export UV_CACHE_DIR="$ROOT/.portal-python-cache"
export UV_NO_PROGRESS=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
"$OLD_PYTHON" -m pip install --only-binary=:all: --target "$BOOTSTRAP/uv" 'uv==0.13.5'
UV="$BOOTSTRAP/uv/bin/uv"
if [[ -z $TARGET_PYTHON ]]; then
  "$UV" python install --no-bin 3.13
  TARGET_PYTHON=$(UV_PYTHON_PREFERENCE=only-managed "$UV" python find 3.13)
fi
"$TARGET_PYTHON" -c 'import sys; assert sys.version_info[:2]==(3,13), "Требуется Python 3.13"; print("Новый интерпретатор:",sys.version.split()[0])'
"$UV" venv --python "$TARGET_PYTHON" "$CANDIDATE"
"$UV" pip install --python "$CANDIDATE/bin/python" --only-binary=:all: -r "$ROOT/requirements.txt"
"$CANDIDATE/bin/python" -m compileall -q "$ROOT/server"
(
  cd -- "$ROOT"
  STATUS_DB="$BOOTSTRAP/check.sqlite3" STATUS_INSECURE_LOCAL=1 "$CANDIDATE/bin/python" - <<'PY'
from fastapi.testclient import TestClient
from server.app import app
with TestClient(app,base_url='http://127.0.0.1') as client:
    assert client.get('/health').status_code==200
    assert client.get('/').status_code==200
print('Проверены импорт, тестовая база, главная страница и /health.')
PY
)
if (( PREPARE )); then echo "Среда подготовлена: $CANDIDATE. Службы не изменены."; exit 0; fi
mkdir -p -- "$(dirname -- "$DROPIN")" "$ROOT/.portal-runtime-backups"
[[ ! -L $DROPIN ]] || { echo 'Настройка запуска является символической ссылкой; переключение отменено.' >&2; exit 2; }
if [[ -e $DROPIN ]]; then cp -p -- "$DROPIN" "$BACKUP"; HAD_DROPIN=1; else : > "$BACKUP.absent"; fi
# Keep every existing uvicorn argument. Only its Python executable changes.
# This staged file is not installed until parsing and validation have completed.
"$CANDIDATE/bin/python" - "$CANDIDATE/bin/python" "$UNIT" "$BOOTSTRAP/runtime.conf" <<'PY'
import pathlib,re,shlex,subprocess,sys
text=subprocess.check_output(['systemctl','show','--value','--property=ExecStart',sys.argv[2]],text=True)
match=re.search(r'argv\[\]=(.*?) ; ignore_errors=',text)
if not match:raise SystemExit('Не удалось безопасно разобрать ExecStart. Служба не изменена.')
if any(char in match[1] for char in ('\\','$','%')):
    raise SystemExit('В ExecStart используются нестандартные подстановки или экранирование. Служба не изменена.')
args=shlex.split(match[1])
if args[1:4]!=['-m','uvicorn','server.app:app']:
    raise SystemExit('Нет ожидаемого запуска uvicorn server.app:app. Служба не изменена.')
if '--port' not in args or args[args.index('--port')+1]!='8000':
    raise SystemExit('Используется нестандартный порт. Служба не изменена.')
if '--host' not in args or args[args.index('--host')+1]!='127.0.0.1':
    raise SystemExit('Используется нестандартный адрес. Служба не изменена.')
args[0]=sys.argv[1]
def quote(value):return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%').replace('$','$$')+'"'
pathlib.Path(sys.argv[3]).write_text('[Service]\nExecStart=\nExecStart='+ ' '.join(map(quote,args))+'\n')
PY
ACTIVATED=1
install -m 0644 -- "$BOOTSTRAP/runtime.conf" "$DROPIN"
systemctl daemon-reload
systemctl restart "$UNIT"
HEALTHY=0
for attempt in {1..20}; do
  if systemctl is-active --quiet "$UNIT" && curl --fail --silent --max-time 2 http://127.0.0.1:8000/health >/dev/null; then HEALTHY=1; break; fi
  sleep 1
done
(( HEALTHY ))
PID=$(systemctl show --value --property=MainPID "$UNIT")
[[ $(readlink -f "/proc/$PID/exe") == "$(readlink -f "$CANDIDATE/bin/python")" ]]
ACTIVATED=0
trap - ERR INT TERM
echo 'Портал работает на отдельном Python 3.13. Системный Python, общая .venv, агенты и другие службы не изменены.'
echo "Среда: $CANDIDATE"
echo "Прежняя настройка запуска: $BACKUP (или отметка .absent)."
