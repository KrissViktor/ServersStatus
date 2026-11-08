# Backup → Raspberry Pi: обратный SSH вместо Tailscale

Для разных сетей и региона, где Tailscale недоступен. Никакого стороннего
VPN/control plane: Windows **сам** открывает исходящее SSH-соединение с Raspi.

```text
Портал на Raspi → 127.0.0.1:18091
                      ↓ зашифрованный обратный SSH-туннель
                  Backup → 127.0.0.1:8091 → llama.cpp
```

- На Windows модель остаётся на loopback, входящие порты не нужны.
- Роутер дома: внешний TCP **2222 → Raspberry Pi TCP 22**.
- На Raspi обратный порт **18091 слушает только 127.0.0.1**, не интернет.
- Отдельный SSH-ключ и пользователь `serversstatus-ai-tunnel`, без shell/PTY,
  agent/X11 forwarding; разрешён только reverse listen `127.0.0.1:18091`.
- Windows Task Scheduler запускает клиент как SYSTEM после перезагрузки;
  reconnect каждые 10 с при ошибке, keepalive, строгая проверка ключа Raspi.
  SYSTEM нужен для фонового запуска с закрытым SSH-ключом; код/настройки/ключ
  доступны только администраторам/SYSTEM, учётная запись модели LocalService
  не получает доступ к этому ключу.

## 1. На Backup: получить публичный SSH-ключ

PowerShell от администратора. Обновить исходники проекта:

```powershell
$dest = 'C:\ServersStatusAISetup'
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/KrissViktor/ServersStatus/archive/refs/heads/main.zip' -OutFile "$dest\source.zip"
Expand-Archive -LiteralPath "$dest\source.zip" -DestinationPath $dest -Force
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$dest\ServersStatus-main\deploy\ai-windows\New-AITunnelKey.ps1"
```

Если OpenSSH Client отсутствует:

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

Затем повторите New-AITunnelKey.ps1. Он показывает строку **ssh-ed25519 …**
из `id_ed25519.pub`: это публичная часть, её нужно перенести на Raspi.
Приватный файл `C:\ProgramData\ServersStatusAI\tunnel\id_ed25519` и ключ API
никому не передавать. Повторный запуск не заменяет уже созданный ключ.

## 2. На Raspberry Pi: разрешить только этот туннель

```bash
cd /opt/ServersStatus
sudo git pull --ff-only origin main
sudo apt-get update
sudo apt-get install -y openssh-server openssl
sudo systemctl enable --now ssh
nano /tmp/backup-ai.pub
```

В nano вставьте **одну публичную строку** из шага 1, сохраните Ctrl+O, Enter,
выйдите Ctrl+X. Это не приватный ключ и не ключ API модели.

```bash
sudo bash /opt/ServersStatus/deploy/ai-ssh/Setup-Raspi.sh /tmp/backup-ai.pub
```

Скрипт проверяет синтаксис и эффективные ограничения sshd, затем перезагружает
его конфигурацию. Прежние настройки других пользователей не заменяются.
Печатаются **публичный host key Raspberry Pi** и SHA256 fingerprint.
Скопируйте строку `ssh-ed25519 …` из этого доверенного сеанса для шага 4.

При нестандартных AllowUsers/AllowGroups SSH-политиках нужно отдельно разрешить
нового пользователя; скрипт не ослабляет эти ограничения и не заменяет весь
sshd_config. При отклонении drop-in предыдущая версия восстанавливается.

## 3. Домашний роутер

После настройки ключей: TCP 2222 снаружи → локальный IP Raspberry Pi, TCP 22.
Внутренний IP Raspi должен оставаться постоянным (например DHCP reservation).
`panel.vikserver.ru` должен разрешаться в домашний статический IP напрямую:
если домен проксируется через CDN, используйте непроксированный домен или IP.

Этот проброс делает существующий SSH Raspi доступным извне, включая прежние
учётные записи. Используйте ключевой вход и по возможности ограничение
исходного IP в роутере/брандмауэре. Скрипт ограничивает новый tunnel-account,
но не меняет пароли/способ входа администратора и не отключает доступ вслепую.

## 4. На Backup: закрепить ключ Raspi и включить автозапуск

PowerShell от администратора:

```powershell
$raspiHostKey = Read-Host 'Вставьте публичную строку ssh-ed25519 из вывода Setup-Raspi'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\ServersStatusAISetup\ServersStatus-main\deploy\ai-windows\Install-AITunnel.ps1' -HostKey $raspiHostKey
```

По умолчанию сервер — `panel.vikserver.ru:2222`. При другом адресе добавьте
`-ServerHost 'ваш-домен-или-IP'`; для другого порта — `-ServerPort 2222`.
Вводите настоящий ключ из шага 2, а не пример и не результат непроверенного
ssh-keyscan: проверка личности Raspi не отключается, known_hosts закрепляется.
Порт модели, служба модели, API-ключ и настройки бэкапов не меняются.

## 5. Проверить на Raspi

```bash
curl --fail --show-error --max-time 15 http://127.0.0.1:18091/health
```

Ожидается `{"status":"ok"}`. Локальный health не требует ключ API.
Это подтверждает туннель и готовность модели, а не наличие чата в портале.
Если модель выгружена из-за паузы/памяти, SSH может работать, но health не ответит.

Диагностика Windows:

```powershell
Get-ScheduledTask -TaskName ServersStatusAI-Tunnel
Get-Content 'C:\ProgramData\ServersStatusAI\tunnel\tunnel.log' -Encoding UTF8 -Tail 30
```

Логи ограничены двумя файлами примерно по 5 Мб. Host key mismatch нельзя
исправлять отключением StrictHostKeyChecking: заново проверьте ключ Raspi.
`Connection refused/timed out` — проверьте проброс/DNS/SSH, `Permission denied` —
публичный ключ и SSH-журнал Raspi, `remote port forwarding failed` — ограничения
или уже занятый обратный порт.

Остановка/удаление Windows-задачи:

```powershell
Stop-ScheduledTask -TaskName ServersStatusAI-Tunnel
Unregister-ScheduledTask -TaskName ServersStatusAI-Tunnel -Confirm:$false
```

Для полного отзыва на Raspi удалите публичный ключ из
`/var/lib/serversstatus-ai-tunnel/.ssh/authorized_keys`. Закройте проброс 2222,
если он больше не нужен. Не удаляйте весь sshd_config/SSH-сервис.

## Следующий шаг

После успешного health портал сможет обращаться к модели через localhost:18091.
Ключ API передадим в отдельный защищённый файл на Raspi локально, без публикации
в чате/Git. Чат, интернет-поиск и доступ к 1С подключаются отдельно.
Tailscale для этого варианта не нужен и Connect-AI.ps1 запускать не требуется.

## Windows: UNPROTECTED PRIVATE KEY FILE / bad permissions

Задача туннеля работает как SYSTEM. Если ключ был создан отдельным пользователем
«Администратор», OpenSSH может отвергнуть его владельца или явные ACE, даже
когда права каталога выглядят правильно. Не заменяйте ключ и не отключайте
проверку подлинности: обновите исходники и выполните от администратора:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\ServersStatusAISetup\ServersStatus-main\deploy\ai-windows\Repair-AITunnelKey.ps1'
```

Скрипт приостанавливает задачу, создаёт защищённый ACL приватного файла только
для SYSTEM и встроенной группы Administrators, устанавливает владельцем эту
группу и запускает задачу снова. SID используются независимо от языка Windows.
Публичный ключ на Raspi и содержимое приватного ключа сохраняются.

После нескольких секунд снова проверьте `/health` на Raspi и последние строки
`tunnel.log` на Windows. Старые ошибки остаются в журнале: смотрите новые метки
времени. Новая генерация/установка туннеля также автоматически исправляет файл.
