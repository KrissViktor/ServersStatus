# Linux-агент: CentOS Stream 9 (btrx24)

Агент использует тот же протокол, историю, бэкапы, удалённые настройки,
прогноз дисков, журнал и Telegram, что и Windows. Отличается только установка
и чтение состояния служб: в Linux используется systemd.

Системный Python, Bitrix, nginx/Apache, SQL и firewall не перенастраиваются.
Для агента создаются отдельные каталог, Python venv и непривилегированный
пользователь. Входящие порты не нужны — только исходящий HTTPS к панели.

## 1. Обновить панель на Raspberry Pi

    cd /opt/ServersStatus
    sudo git pull --ff-only origin main
    sudo systemctl restart serversstatus

## 2. Создать ключ

В панели: «Управление агентами» → добавить linux-btrx24. Сохраните полученный
ключ у себя, не присылайте его в чат.

## 3. Первая установка на CentOS Stream 9

Дальше команды выполняются НА LINUX-СЕРВЕРЕ btrx24 от root.
CentOS 9 по умолчанию может использовать Python 3.9: не меняем его, устанавливаем
параллельно Python 3.11.

    dnf install -y python3.11 python3.11-pip git
    python3.11 --version

    mkdir -p /opt/serversstatus-agent
    git clone https://github.com/KrissViktor/ServersStatus.git /opt/serversstatus-agent/current

    python3.11 -m venv /opt/serversstatus-agent/.venv
    /opt/serversstatus-agent/.venv/bin/python -m pip install -r /opt/serversstatus-agent/current/agent/requirements-linux.txt

Если каталог current уже существует, не удаляйте его: используйте раздел
обновления ниже. Если pip сообщает о необходимости сборки psutil из исходников,
установите gcc и python3.11-devel через dnf и повторите установку зависимостей.

## 4. Пользователь и конфигурация

    id serversstatus-agent || useradd --system --home-dir /var/lib/serversstatus-agent --shell /sbin/nologin serversstatus-agent
    install -d -o serversstatus-agent -g serversstatus-agent -m 750 /var/lib/serversstatus-agent

    test -e /var/lib/serversstatus-agent/config.json || install -o root -g serversstatus-agent -m 640 /opt/serversstatus-agent/current/agent/config.linux.example.json /var/lib/serversstatus-agent/config.json

    nano /var/lib/serversstatus-agent/config.json

Заполните server_url, agent_id и token. Адрес панели уже указан. ID должен
совпадать с зарегистрированным linux-btrx24. Токен остаётся только в файле.
Список services пока можно оставить пустым. Бэкапы задаются Linux-путями,
например /var/backups/sql. Произвольные файлы можно проверять с отключённым
date_from_filename; формат даты из имени пока ориентирован на SQL .bak.

## 5. Установить автозапуск

    cp /opt/serversstatus-agent/current/deploy/serversstatus-linux-agent.service /etc/systemd/system/serversstatus-agent.service
    systemctl daemon-reload
    systemctl enable --now serversstatus-agent
    systemctl status serversstatus-agent --no-pager

Первый отчёт должен появиться после запуска; затем агент отправляет данные
каждые 10 секунд.
Логи:

    journalctl -u serversstatus-agent -n 30 --no-pager

Дополнительный журнал с ротацией:
 /var/lib/serversstatus-agent/agent.log

Кэш настроек панели:
 /var/lib/serversstatus-agent/config.json.remote.json

## 6. Настроить службы в панели

В настройках linux-btrx24 укажите фактические systemd-имена, по одному на строку.
Примеры: nginx.service, httpd.service, mysqld.service или mariadb.service.
Не добавляйте все примеры автоматически: отсутствующая служба будет ошибкой.
Посмотреть работающие службы на этом сервере:

    systemctl list-units --type=service --state=running --no-pager

Автоматический поиск 1С/SQL работает для mssql-server.service и служб с
именами srv1cv8..., srv1c..., ras1c...; он отключается существующим флажком.
Остальные службы (в том числе Bitrix) задаются вручную. Никаких команд restart/stop
агент не выполняет. Shell не используется; список units передаётся отдельными
аргументами с проверкой имён.

Для чтения защищённых бэкапов выдайте пользователю агента права чтения/прохода
только к нужным папкам через существующую группу или ACL. Агент не запускается
от root, поэтому защищённый каталог может отображаться как недоступный.
RDP/WTS предназначен для Windows и на Linux в панели скрыт; xrdp пока не собирается.

## RAM и частота CPU

RAM «занято» рассчитывается как total - available; освобождаемый кэш Linux
не считается безусловно занятым приложениями. Проценты и объём берутся из
одного снимка. Частота psutil переводится из МГц в ГГц; это значение ОС, на Windows
оно может быть номинальным. При отсутствии данных не показывается выдуманная
частота; если доступна только максимальная, она явно подписывается «до».

## Обновление Linux-агента

    cd /opt/serversstatus-agent/current
    git pull --ff-only origin main
    /opt/serversstatus-agent/.venv/bin/python -m pip install -r agent/requirements-linux.txt
    systemctl restart serversstatus-agent

Конфигурация с ключом и кэш лежат вне репозитория, обновление их не меняет.
Для остановки автозапуска:

    systemctl disable --now serversstatus-agent

После установки проверьте появление данных, чтение нужных папок/служб и
автозапуск после плановой перезагрузки CentOS. На рабочем btrx24 установка
из среды разработки не выполнялась.

## Отображаемые диски Linux

Для контроля свободного места Linux передаёт только корневой том /.
Snap/squashfs и служебные bind mounts исключены. Панель также фильтрует старые
отчёты, поэтому достаточно обновить Raspberry Pi; обновление Linux-агента
дополнительно уменьшает объём отправляемых данных.
