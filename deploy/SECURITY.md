# Защита входа и ограничение HTTP-флуда

После двух неверных паролей с одного IP веб-доступ запрещается на 15 минут.
Следующий эпизод из двух ошибок после истечения срока даёт 45 минут, далее 135,
405 и так далее ×3 без заданного верхнего предела. Срок и ступень хранятся в SQLite.
Запросы во время запрета не продлевают срок. Успешный вход сбрасывает ошибки,
но сохраняет ступень. Все пользователи за одним NAT разделяют этот запрет.
Смена имени пользователя не сбрасывает ошибки IP.

Отчёты агентов не отключаются из-за блокировки веб-входа с общего IP, но на них
действуют общие лимиты запросов и проверка индивидуального ключа.

Ограничители:
- На IP: запас 60 запросов, восстановление 5 запросов/с.
- На процесс: запас 120, восстановление 30 запросов/с.
- Вход: запас 4 на IP, восстановление 1 за 30 с; глобально запас 10, далее 1/с.
- Одновременно рассчитываются не более 2 scrypt-хешей.
- Память ограничителя: максимум 10 000 IP. Лимиты HTTP-флуда сбрасываются после
  перезапуска; блокировки входа сохраняются в SQLite.
- Тело входа до 4096 байт, общие тела до 65536 байт.
- Избыточные запросы получают 429 и Retry-After, большие тела — 413.
- Шаблон Caddy отказывает путям сканеров до приложения. User-Agent не считается
  надёжным доказательством, что запрос отправлен человеком.

Это защита от перебора и части HTTP-флуда, а не гарантия от DDoS.
Заполнение домашнего интернет-канала необходимо фильтровать у провайдера или
через внешний защищённый reverse proxy/WAF. Распределённая атака может занять
общий лимит и временно мешать пользователям. Таймер уведомлений работает отдельно.

## Обновление приложения и Uvicorn

На Raspberry Pi:

    cd /opt/ServersStatus
    sudo git pull --ff-only origin main
    sudo cp -a /etc/systemd/system/serversstatus.service /etc/systemd/system/serversstatus.service.before-security
    sudo cp deploy/serversstatus.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl restart serversstatus

Если unit-файл менялся вручную, сохраните нужные изменения из резервной копии.
Добавлены limit-concurrency 32, backlog 128, keep-alive 5 с, предел неполного
заголовка 16 КиБ. Access log отключён, чтобы флуд не заполнял журнал каждой
HTTP-записью. Журнал ошибок остаётся.

## Caddy: IP, таймауты и сканеры

Сохраните конфигурацию и отредактируйте её, не удаляя другие сайты:

    sudo cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-security
    sudo nano /etc/caddy/Caddyfile

В блоке panel.vikserver.ru замените одиночную строку reverse_proxy на:

    @scanners path /.env /.git/* /wp-login.php /wp-admin/* /phpmyadmin/*
    respond @scanners 404
    reverse_proxy 127.0.0.1:8000 {
        header_up X-Status-Client-IP {remote_host}
        transport http {
            dial_timeout 3s
            response_header_timeout 15s
        }
    }

Сохраните существующие request_body max_size 64KB и защитные заголовки.
В глобальный блок Caddy в начале файла можно добавить таймауты из deploy/Caddyfile:

    {
        servers {
            max_header_size 16KB
            timeouts {
                read_header 5s
                read_body 15s
                write 30s
                idle 30s
            }
        }
    }

Если глобальный блок уже есть, объедините параметры, не создавайте второй.

    sudo caddy validate --config /etc/caddy/Caddyfile
    sudo systemctl reload caddy

Если validate не прошёл, не выполняйте reload. Конфигурацию нужно проверить
на версии Caddy на Raspberry Pi; в среде разработки Caddy не установлен.

Приложение слушает только 127.0.0.1:8000 с no-proxy-headers Uvicorn. IP читается
из X-Forwarded-For, который стандартный Caddy формирует из адреса посетителя;
X-Status-Client-IP — резервный. Заголовки доверяются только от loopback.
Не открывайте порт 8000 наружу. При добавлении CDN/другого посредника перед Caddy
настройка доверенных IP-сетей этого посредника должна выполняться отдельно.

## Если случайно заблокировали себя

По SSH на Raspberry Pi:

    cd /opt/ServersStatus
    sudo -u serversstatus env STATUS_DB=/var/lib/serversstatus/status.sqlite3 .venv/bin/python -m server.security_cli list

    sudo -u serversstatus env STATUS_DB=/var/lib/serversstatus/status.sqlite3 .venv/bin/python -m server.security_cli unblock ВАШ_ВНЕШНИЙ_IP

Это снимает текущий запрет, сохраняя ступень увеличения срока. Не подставляйте
локальный IP Raspberry Pi вместо IP посетителя. Не проверяйте рабочий вход
двумя ошибками без возможности SSH-разблокировки. Windows-агенты обновлять не нужно.

Для полного списка процессов предусмотрено отдельное исключение 2MB только
для /api/processes/*; остальные маршруты сохраняют 64KB. См. PROCESSES.md.
