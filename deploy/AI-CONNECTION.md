# Raspberry Pi ↔ Backup через разные сети

**Текущий выбранный вариант:** [обратный SSH](ai-ssh/README.md), поскольку
Tailscale недоступен в сети Backup. Инструкция ниже оставлена как альтернатива
для сетей с доступным Tailscale.

Модель уже работает на `Backup / WIN-CU629F0N7II / windows-02`:
локальный тест показал 6,27 токена/с и ответ за 4,9 с. Цель этого этапа —
соединить Raspberry Pi и Windows через Tailscale. **Одна локальная сеть не нужна.**
Tailscale строит зашифрованное соединение через интернет и при необходимости
использует relay. Это не создаёт публичного доступа к API модели.

## 1. Raspberry Pi

Установите официальный клиент и войдите в свою сеть Tailscale:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

В выводе будет ссылка для входа. Откройте её в браузере, создайте аккаунт/войдите
и подтвердите Raspberry Pi. Ссылки входа и auth keys не присылайте в чат.
Linux-служба tailscaled запускается автоматически после перезагрузки.

```bash
tailscale status
tailscale ip -4
```

## 2. Backup / Windows Server 2022

На **Backup**, а не на сервере «Терминалы», установите официальный Tailscale:
https://tailscale.com/download/windows

Войдите **в тот же аккаунт / ту же tailnet**, что на Raspberry Pi.
Если используется device approval, подтвердите обе машины в Tailscale Admin.
Они должны видеть друг друга в `tailscale status`.

Обновите исходники проекта на Backup (модель не скачивается заново):

```powershell
$dest = 'C:\ServersStatusAISetup'
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/KrissViktor/ServersStatus/archive/refs/heads/main.zip' -OutFile "$dest\source.zip"
Expand-Archive -LiteralPath "$dest\source.zip" -DestinationPath $dest -Force
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$dest\ServersStatus-main\deploy\ai-windows\Connect-AI.ps1"
```

PowerShell должен быть запущен от администратора. Скрипт:

- проверяет вход в Tailscale и работоспособность локальной модели;
- включает unattended mode, чтобы сеть работала после выхода из Windows;
- публикует `http://127.0.0.1:8091` через **закрытый HTTPS Tailscale Serve**
  на порту 8443. Сам llama-server остаётся на loopback;
- не включает Funnel, subnet routing, exit node и не меняет брандмауэр;
- отказывается перезаписывать чужой Serve на 8443 или работать при включённом
  Funnel. Текущая идентичная конфигурация допускает повторный запуск.

При первом включении Serve может появиться ссылка на разрешение HTTPS/сертификатов
в Tailscale. Откройте её, подтвердите и повторите Connect-AI.ps1. В настройках DNS
tailnet должна быть включена MagicDNS. Для сертификатов Tailscale HTTPS имя узла
может быть видно в публичных Certificate Transparency logs; содержимое API от
этого не становится публичным.

В конце появится адрес примерно:

```text
Private AI URL: https://win-cu629f0n7ii.tailXXXX.ts.net:8443
```

Открывать порт 8091/8443 на роутере или менять host модели на 0.0.0.0 не нужно.

## 3. Проверить с Raspberry Pi

Подставьте **реальный адрес из вывода Connect-AI**, без придуманного tailXXXX:

```bash
tailscale status
curl --fail --show-error --max-time 30 'https://ИМЯ-ИЗ-ВЫВОДА.ts.net:8443/health'
```

Ожидается `{"status":"ok"}`. Проверка health не требует пересылки API-ключа.
Если не отвечает: проверьте вход обеих машин в одну tailnet, approval, DNS/HTTPS,
паузы модели и наличие свободной RAM. В tailnet с ограничивающими grants/ACL
разрешите соединение **Raspberry Pi → Backup TCP 8443**; не заменяйте весь
существующий ACL и не открывайте все устройства всем. Стандартная новая tailnet
может разрешать соединения между всеми вашими устройствами: перед добавлением
других пользователей/устройств сузьте доступ к модели до Raspberry Pi.

Отключение только AI Serve, без сброса остальных сервисов Tailscale:

```powershell
& "$env:ProgramFiles\Tailscale\tailscale.exe" serve --https=8443 off
```

## Следующий этап

Нужны только закрытый HTTPS-адрес модели и результат `/health` с Raspberry Pi.
**API-ключ не отправлять в чат**: для подключения портала он будет записан локально
в защищённый файл на Raspi. Сам чат/интернет-поиск/1С этим этапом ещё не добавляются.
Модель не получает доступ к консоли или произвольному выполнению команд.
