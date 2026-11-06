# Только Telegram через Hysteria2 на Raspberry Pi

Схема: уведомления → локальный SOCKS5 → Hysteria2-сервер → Telegram.
Если ваш сервер уже направляет этот выход через VLESS, эта часть остаётся на нём.
На Raspberry Pi нужен только Hysteria2-клиент. Маршруты ОС и глобальные HTTP_PROXY /
HTTPS_PROXY не меняются. Это не перехват всего трафика Telegram на устройстве:
прокси используют только запросы Bot API проекта ServersStatus.

## 1. Обновить проект и зависимости

```bash
cd /opt/ServersStatus
sudo git pull --ff-only origin main
sudo .venv/bin/pip install -r requirements.txt
```

Добавлена httpx с поддержкой SOCKS. Windows-агенты обновлять не требуется.

## 2. Установить Hysteria2-клиент ARM64

Проверьте `uname -m`: следующие команды для `aarch64`. Если архитектура другая,
не запускайте их. Если Hysteria уже установлена, не перезаписывайте её: сначала
проверьте `command -v hysteria` и `hysteria version`, затем скорректируйте ExecStart.

Загрузка из официального репозитория [apernet/hysteria](https://github.com/apernet/hysteria/releases):

```bash
curl --proto '=https' --tlsv1.2 -fL --retry 3 \
  https://github.com/apernet/hysteria/releases/latest/download/hysteria-linux-arm64 \
  -o /tmp/hysteria-linux-arm64
sudo install -m 755 /tmp/hysteria-linux-arm64 /usr/local/bin/hysteria
/usr/local/bin/hysteria version
```

TLS-проверка при загрузке включена. Команда получает текущий официальный релиз;
для воспроизводимой установки сохраните номер версии, показанный командой version.
Если загрузка не проходит, не отключайте TLS-проверку и не используйте случайные зеркала.

## 3. Сохранить ссылку в защищённом конфиге

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin hysteria-client
sudo install -d -o root -g hysteria-client -m 750 /etc/hysteria-telegram
sudo install -o root -g hysteria-client -m 640 \
  deploy/hysteria-client.yaml.example /etc/hysteria-telegram/client.yaml
sudo nano /etc/hysteria-telegram/client.yaml
```

Замените только значение `server` своей полной ссылкой `hy2://...` либо
`hysteria2://...`. Ссылка должна оставаться внутри двойных кавычек YAML.
Не присылайте ссылку в чат, не помещайте её в командную строку или Git.
Остальные поля оставьте:

```yaml
tls:
  insecure: false
socks5:
  listen: 127.0.0.1:1080
```

Параметры SNI/obfs в ссылке должны соответствовать работающему Windows-подключению.
Если в ссылке есть `insecure=1` или `insecure=true`, не копируйте её как есть:
нужно настроить доверие сертификату (правильный SNI, доверенный CA или проверенный
отпечаток сертификата) по [официальной конфигурации клиента](https://v2.hysteria.network/docs/advanced/Full-Client-Config/).
Не отключайте проверку сертификата для обхода ошибки.
Hysteria2 использует UDP/QUIC: Raspberry Pi должен иметь доступ к UDP-порту вашего
Hysteria2-сервера. Пробрасывать новый входящий порт на домашнем роутере не нужно.

## 4. Автозапуск локального прокси

```bash
sudo cp deploy/serversstatus-hysteria.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now serversstatus-hysteria
systemctl is-active serversstatus-hysteria
```

Если запуск не удался, изучите журнал **локально**:

```bash
sudo journalctl -u serversstatus-hysteria -n 30 --no-pager
```

Перед отправкой журнала кому-либо удалите ссылку, пароль, ключ obfs и другие
секреты. Клиент сторонний, его вывод может содержать параметры подключения.

Проверка доступа к Telegram с удалённым разрешением DNS через SOCKS5:

```bash
curl --fail --max-time 20 --socks5-hostname 127.0.0.1:1080 https://api.telegram.org/
```

Ожидается ответ HTTP от Telegram без ошибок соединения/TLS. Само наличие слушающего
порта не подтверждает работоспособность VPN. SOCKS5 привязан только к loopback.

## 5. Направить уведомления через прокси

Откройте существующий файл, сохраняя токен и ID чата:

```bash
sudo nano /etc/serversstatus-telegram.env
```

Добавьте строку:

```dotenv
STATUS_TELEGRAM_PROXY=socks5h://127.0.0.1:1080
```

Проверка отправки (если боту уже отправлен /start и задан ID):

```bash
sudo bash deploy/telegram-command.sh --test
```

Определение ID при необходимости тоже пойдёт через прокси:

```bash
sudo bash deploy/telegram-command.sh --discover-chat
```

Далее включите таймер по TELEGRAM.md, если ещё не включён. Если включён —
он прочитает новую настройку при следующем запуске. Для немедленной проверки:

```bash
sudo systemctl start serversstatus-notify.service
```

SOCKS использует удалённое разрешение имени Telegram. При ошибке прокси прямой
запрос не выполняется, инцидент остаётся для повторной отправки. TLS Telegram
проверяется независимо от шифрования Hysteria2. Отключить прокси для уведомлений
можно удалением только строки STATUS_TELEGRAM_PROXY из env-файла.

Конфигурацию Hysteria2 и доставку нужно проверить на вашем Raspberry Pi: ссылка
и VPN-сервер недоступны среде разработки. Работоспособность Windows-клиента сама
по себе не подтверждает UDP-доступ и доверие сертификату на Raspberry Pi.
