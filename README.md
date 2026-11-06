# ServersStatus

Единый центр мониторинга Windows Server 2019 / Windows 10 на Raspberry Pi 5 (Linux, ARM64).
Python 3.11+, FastAPI, SQLite, HTML. Агенты отправляют отчёты через HTTPS раз в минуту.

## Что реализовано

Вход с хешированием паролей (scrypt), сессии на 8 часов, ограничение попыток входа,
индивидуальные ключи агентов (в базе хранятся только хеши), CPU, RAM, диски,
время работы, Windows-службы, свежесть файлов бэкапов. История хранится 30 дней.
Панель показывает карточки серверов, индикаторы CPU/RAM, диски и состояния служб/бэкапов.
Страница автоматически обновляется каждые 30 секунд. Графики, настройки через UI,
уведомления, SQL msdb и управление службами — следующие этапы, они ещё не реализованы.

## Локальная разработка

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m server.cli create-admin admin
python -m server.cli add-agent sql-server-01
# Только для локальной разработки без HTTPS:
STATUS_INSECURE_LOCAL=1 python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

Рабочая папка — корень проекта. Ключ из add-agent показывается один раз: перенесите его
в agent/config.json. Не коммитьте этот файл. Повторная регистрация существующего имени
отклоняется. Пароли и ключи не передавайте в аргументах командной строки.

## Raspberry Pi: установка и автоматический запуск

Используйте 64-битный Linux и Python 3.11 или новее. Команды выполняются на Raspberry Pi,
не в облачной среде разработки. Измените путь клонирования, если проект уже скачан.

```sh
sudo apt update
sudo apt install python3-venv git
sudo git clone https://github.com/KrissViktor/ServersStatus.git /opt/ServersStatus
sudo python3 -m venv /opt/ServersStatus/.venv
sudo /opt/ServersStatus/.venv/bin/pip install -r /opt/ServersStatus/requirements.txt
sudo useradd --system --home /var/lib/serversstatus --shell /usr/sbin/nologin serversstatus
sudo install -d -o serversstatus -g serversstatus -m 700 /var/lib/serversstatus
cd /opt/ServersStatus
sudo -u serversstatus env STATUS_DB=/var/lib/serversstatus/status.sqlite3 .venv/bin/python -m server.cli create-admin admin
sudo -u serversstatus env STATUS_DB=/var/lib/serversstatus/status.sqlite3 .venv/bin/python -m server.cli add-agent sql-server-01
sudo cp deploy/serversstatus.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now serversstatus
curl --fail http://127.0.0.1:8000/health
```

Установите Caddy из официального репозитория для вашей ОС по https://caddyserver.com/docs/install.
Создайте DNS A запись домена на статический домашний IP. Замените status.example.com
в deploy/Caddyfile и установите его как /etc/caddy/Caddyfile. Проверьте
`sudo caddy validate --config /etc/caddy/Caddyfile`, затем `sudo systemctl reload caddy`.
Пробросьте TCP 80 и 443 на Raspberry Pi для сертификата и HTTPS. Порт 8000 наружу
не открывайте. Проверьте `/health` через HTTPS с другой сети и вход в панель.
Не задавайте STATUS_INSECURE_LOCAL в рабочем развёртывании.
Для доступа только по IP потребуется отдельная настройка доверенного сертификата;
первое развёртывание рекомендуем делать с доменом.

## Windows-агент

Установите 64-битный Python 3.11/3.12 для всех пользователей в каталог, доступный службе.
Скопируйте проект в `C:\ServersStatus`. В терминале администратора:

```powershell
cd C:\ServersStatus
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r agent\requirements-windows.txt
Copy-Item agent\config.example.json agent\config.json
# Теперь заполните config.json: URL, имя, индивидуальный ключ, службы и папки.
.\.venv\Scripts\python.exe -m agent.client agent\config.json
# После проверки отчёта остановите Ctrl+C и установите службу:
.\.venv\Scripts\python.exe agent\windows_service.py --startup auto install
.\.venv\Scripts\python.exe agent\windows_service.py start
sc.exe failure ServersStatusAgent reset= 86400 actions= restart/10000/restart/30000/restart/60000
```

Ограничьте права на config.json администраторами и учётной записью службы.
По умолчанию служба запускается от LocalSystem. Для сетевых папок настройте отдельную
учётную запись службы с правами чтения и используйте UNC-пути, а не подключённые диски.
Убедитесь, что после перезагрузки Windows отчёты снова появляются в панели.
Установка Windows-службы должна быть проверена на реальной Windows: Linux этого не проверяет.

Для бэкапов настройте отдельную папку/правило для каждой базы: иначе свежий файл одной
базы может скрыть отсутствие копии другой. `observing` — размер/mtime ещё не подтверждены
двумя опросами; `fresh` — файл стабилен и свеж; `stale` — просрочен; `missing` — файлов нет.
Стабильность файла не подтверждает целостность SQL-бэкапа или завершение копирования
при длительной паузе. Для надёжного контроля нужны журнал переноса и тест восстановления.

## Проверки

```sh
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Резервируйте SQLite через sqlite3 backup API либо при остановленном сервисе.
Мониторинг пока доступен всем вошедшим администраторам; ролей пользователей нет.
История накапливается в SQLite, графиков и API чтения истории пока нет.

## Windows без установки Python: EXE

GitHub Actions → **Build Windows agent** → последний успешный запуск →
Artifacts → **ServersStatus-Windows-x64**. Распакуйте архив и запустите
`ServersStatusSetup.exe` от администратора. Введите URL панели, зарегистрированное
имя и ключ агента. Установщик сначала отправит проверочный отчёт, затем установит
службу с автоматическим запуском. Первый отчёт проверки содержит нулевые показатели;
настоящие показатели придут от службы. Отдельный Python не нужен.

Сборка выполняется Windows runner GitHub после изменений агента. Перед упаковкой
установщика CI проверяет регистрацию, запуск и остановку собранной службы.
Это не заменяет проверку на Windows Server 2019 / Windows 10 и после перезагрузки.
EXE пока без цифровой подписи издателя.

Расположение файлов:
- `%ProgramFiles%\ServersStatus\ServersStatusService.exe` — исполняемый файл службы;
- `%ProgramData%\ServersStatus\config.json` — конфигурация и ключ;
- `%ProgramData%\ServersStatus\agent.log` — журнал ошибок (с ротацией).

Каталог данных ограничен SYSTEM и администраторами. Для первого подключения
используется LocalSystem; доступ к сетевым бэкапам настраивается отдельно.

Для обновления/удаления в PowerShell администратора:

```powershell
& "$env:ProgramFiles\ServersStatus\ServersStatusService.exe" stop
# Дождитесь состояния Stopped:
Get-Service ServersStatusAgent
& "$env:ProgramFiles\ServersStatus\ServersStatusService.exe" remove
```

Затем можно запускать новый установщик. Настройки сохраняются, правила бэкапов
и служб установщик не сбрасывает. Полное удаление каталогов выполняйте только
после удаления службы; в каталоге данных хранится ключ подключения.

## Управление агентами в панели

После входа откройте «Управление агентами». Создайте идентификатор из латинских
букв, цифр, дефисов и подчёркиваний (до 64 символов). Ключ показывается только в
ответе на создание; в базе хранится его хеш. Запишите имя и ключ в EXE-установщик.
Существующие агенты после обновления сервера продолжают работать.

Перевыпуск сразу отключает старый ключ и сохраняет историю. На Windows измените
`token` в `%ProgramData%\ServersStatus\config.json` от администратора, затем:

```powershell
Restart-Service ServersStatusAgent
```

Если агент установлен старым способом из Python, конфигурация находится в
`C:\ServersStatus\agent\config.json`.
Удаление требует ввести точное имя и удаляет регистрацию вместе с историей;
саму Windows-службу нужно остановить/удалить отдельно. Страница управления не
обновляется автоматически, чтобы не прерывать ввод и сохранение ключа.
