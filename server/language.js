/* UI labels only. Report contents and integration payloads stay in the source language. */
(() => {
  const key='serversstatus.language';
  const translations=new Map(`
Язык сайта|Site language
Тема сайта|Site theme
Системная|System
Светлая|Light
Тёмная|Dark
Войти|Sign in
Войти в панель|Open dashboard
Выйти|Sign out
Логин|Username
Пароль|Password
Проверяем данные…|Signing in…
Неверный логин или пароль.|Incorrect username or password.
Слишком много попыток. Попробуйте позже.|Too many attempts. Try again later.
Не удалось войти. Повторите попытку.|Sign-in failed. Try again.
Не удалось связаться с порталом. Повторите попытку.|Could not reach the portal. Try again.
Состояние серверов|Server health
в одном месте|in one place
Server Pulse показывает нагрузку, свободное место, состояние служб и резервных копий. По истории замеров можно понять, когда началась проблема и что происходило с сервером в тот момент.|Server Pulse tracks resource usage, free space, services, and backups. Historical reports show when an issue started and what was happening on the server at the time.
Посмотреть пример ↓|View demo ↓
Как это работает|How it works
Последние 60 минут · пример|Last 60 minutes · demo
Как выглядит обзор|Dashboard preview
Вымышленные серверы и показатели|Sample servers and metrics
Пример списка серверов|Sample server list
Сервер|Server
Серверы|Servers
Состояние|Status
Диск|Disk
Диск почти заполнен|Disk nearly full
На связи|Online
Пример мониторинга сайтов|Website monitoring demo
TLS действителен|TLS certificate valid
TLS истекает через 9 дней|TLS expires in 9 days
Агенты собирают замеры|Agents collect measurements
Агенты Windows и Linux отправляют метрики, сведения о дисках, службах и резервных копиях по HTTPS.|Windows and Linux agents send metrics, disk, service, and backup data over HTTPS.
Портал хранит историю|The portal stores history
Выбирайте период, сравнивайте серверы и открывайте снимок исходного отчёта по точке графика.|Choose a date range, compare servers, and inspect the original report behind a chart point.
Уведомления помогают реагировать|Get notified when something changes
Портал показывает инциденты, а мониторы сайтов проверяют HTTP и сроки сертификатов. Предупреждения можно получать в Telegram.|The portal shows incidents and checks HTTP responses and certificate expiry. Alerts can be sent to Telegram.
От замера до решения|From measurement to resolution
Пример инцидента|Sample incident
Мало места на диске|Low disk space
Диск заполнился на 91%|Disk usage reached 91%
На обзоре появилось предупреждение.|A warning appeared on the dashboard.
Открыли снимок сервера|Opened a server snapshot
По выбранной точке проверили нагрузку, свободное место и состояние бэкапов.|The selected report showed resource usage, free space, and backup status.
Место освободилось|Disk space was freed
Новый отчёт агента подтвердил восстановление.|A new agent report confirmed recovery.
Для ежедневной работы|For day-to-day operations
CPU, RAM и диски на общей шкале. Откройте снимок по точке, чтобы увидеть исходный отчёт.|CPU, RAM, and disks share a timeline. Select a point to open the original report.
Прогноз заполнения дисков, повторяющиеся сбои и бэкапы, требующие проверки.|Disk usage forecasts, recurring incidents, and backups that need attention.
Ожидаемый HTTP-код, время отклика, срок действия TLS и история проверок.|Expected HTTP status, latency, TLS expiry, and check history.
Загрузка CPU, демонстрационные данные|CPU usage, sample data
Занятость RAM, демонстрационные данные|RAM usage, sample data
Заполненность диска, демонстрационные данные|Disk usage, sample data
Основные разделы|Main navigation
Разделы портала|Portal sections
Путь страницы|Breadcrumbs
Группы|Groups
Группы серверов|Server groups
Аналитика|Analytics
Проблемы|Issues
План на неделю|Weekly plan
Обновления|Updates
Администрирование|Administration
Настройки|Settings
Настройки мониторинга|Monitoring settings
Большой экран|Wallboard
Экран|Wallboard
Обзор серверов|Server overview
Карточки|Cards
Таблица|Table
Обычные|Standard
Компактные|Compact
Карта|Map
Связи|Dependencies
Связи серверов|Server dependencies
Сравнение|Compare
Сравнение серверов|Compare servers
Сводка за сутки|Daily summary
Всего|Total
Онлайн|Online
Нет связи|Offline
Диски от 85%|Disks at 85% or above
Поиск|Search
Показать|Show
Группа|Group
Все группы|All groups
Все серверы|All servers
Есть проблемы|Has issues
Сбросить|Reset
По названию|By name
По числу проблем|By issue count
По состоянию связи|By connection status
По загрузке CPU|By CPU usage
По занятости RAM|By RAM usage
По заполнению дисков|By disk usage
По доступности|By uptime
По возрасту отчёта|By report age
Возрастание|Ascending
Убывание|Descending
Сортировка серверов|Sort servers
Порядок серверов|Server order
Изменить направление сортировки|Reverse sort order
Процессор|Processor
Оперативная память|Memory
Последний отчёт|Latest report
Отчёты поступают|Receiving reports
Ожидаем первый отчёт агента|Waiting for the first agent report
Проблем по полученным данным нет|No issues in the latest report
Всё в порядке|All systems operational
Нет проблем без отметки|No unacknowledged issues
Управление отметками|Manage acknowledgements
Доступность|Uptime
Доступность · 24 ч|Uptime · 24 h
Нет данных|No data
История нагрузки|Resource history
ИСТОРИЯ НАГРУЗКИ|RESOURCE HISTORY
Период истории|History range
15 минут|15 minutes
Час|Hour
6 часов|6 hours
Последние сутки|Last 24 hours
Неделя|Week
30 дней|30 days
С|From
По|To
Показать по датам|Apply dates
Среднее CPU|Average CPU
Среднее RAM|Average RAM
Пик CPU|Peak CPU
Пик RAM|Peak RAM
Минимум CPU|Minimum CPU
Минимум RAM|Minimum RAM
Заполненность дисков|Disk usage
Заполненность диска|Disk usage
Сеть|Network
Дисковые операции|Disk I/O
Дисковое устройство|Disk device
Сетевой интерфейс|Network interface
История инцидентов|Incident history
Загрузка…|Loading…
Повторить загрузку|Retry
Снимок сервера|Server snapshot
Исходные отчёты|Raw reports
Закрыть|Close
Внешний вид|Appearance
Тема сохраняется в этом браузере.|The theme is saved in this browser.
Настройки и обслуживание портала|Portal settings and maintenance
Управление агентами|Agent management
Добавить компьютер|Add computer
Пользователи|Users
Добавить пользователя|Add user
Создать пользователя|Create user
Добавить монитор|Add monitor
Добавить или изменить связь|Add or edit dependency
Сохранить связь|Save dependency
Сеансы портала|Portal sessions
Текущие|Active
Завершённые|Ended
Неудачные входы|Failed sign-ins
Завершить сеанс|End session
Сохранить|Save
Добавить|Add
Удалить|Delete
Резервные копии|Backups
Службы|Services
Процессы|Processes
Диски|Disks
Telegram-бот работает|Telegram bot is working
Telegram-бот не работает|Telegram bot is unavailable
В норме|Healthy
Предупреждения|Warnings
Нет проверок|No checks
За этот период проверок нет.|No checks in this period.
На выбранном участке проверок нет.|No checks in this segment.
Выберите участок шкалы, чтобы увидеть проверки и длительность сбоев.|Select a segment to see checks and outage durations.
HTTP снова отвечает|HTTP service recovered
Сбой продолжается|Outage ongoing
Восстановление не подтверждено|Recovery unconfirmed
Первый сбой|First failed check
Последний сбой|Last failed check
Восстановление|Recovery
Длительность по замерам|Duration based on checks
Длительность пока неизвестна.|Duration is unknown.
Начало и восстановление определяются по проверкам внутри выбранного периода.|Outage start and recovery are based on checks within the selected period.
Проверки участка|Checks in this segment
На паузе|Paused
Последняя проверка|Last check
Сбросить даты|Reset dates
Сайты для мониторинга пока не добавлены.|No monitored websites yet.
Были проблемы за сутки|Issues in the last 24 hours
РКН|RKN
Новости|News
Новости портала|Portal news
Что нового|What's new
Все обновления →|All updates →
записей из Git|Git entries
Все новости пишется на языке разработчикам в комитах git hub.|News entries use the original language of the developers' GitHub commits.
Раздел|Category
Агенты|Agents
Проверки и сборки|Checks and builds
Проект|Project
Открыть коммит ↗|Open commit ↗
Записей по выбранным условиям нет.|No entries match the filters.
Предыдущие обновления →|Earlier updates →
История проверок|Check history
Последние проверки|Recent checks
Интервал, секунд|Interval, seconds
Ожидаемый HTTP-код|Expected HTTP status
Название|Name
Уведомлять в Telegram|Send Telegram alerts
Сверять домен с реестром РКН|Check against the RKN registry
Доступен|Available
Ожидает проверки|Awaiting check
Выключено|Disabled
Ошибка соединения|Connection error
Скоро истекает|Expiring soon
Ошибка сертификата|Certificate error
Пауза|Pause
Возобновить|Resume
Журнал событий|Event log
Суточные сводки|Daily summaries
Пересчитать сводки|Rebuild summaries
Более ранние записи →|Older entries →
Мониторинг|Monitoring
Обслуживание|Maintenance
Доступ|Access
Отмеченные проблемы|Acknowledged issues
Кто отметил «Всё окей», комментарии и возврат предупреждений.|See who acknowledged an issue, review comments, and restore alerts.
Площадки, роли и состав групп.|Sites, roles, and group membership.
Добавление серверов, ключи доступа и снятие защиты для работы с консолью.|Register servers, manage access keys, and unlock console access.
Добавление серверов и управление доступом агентов.|Register servers and manage agent access.
Обновления агентов|Agent updates
Версии Windows и Linux, установка обновлений и история выполнения.|Windows and Linux versions, update installation, and deployment history.
Контроль портала|Portal health
База данных, свободное место, фоновые задачи и резервные копии.|Database, free space, background jobs, and backups.
Состояние сервера, на котором работает панель мониторинга.|Health of the server running the monitoring portal.
Telegram-бот|Telegram bot
Состояние бота, уведомления и отчёты.|Bot health, notifications, and reports.
ИИ-помощник|AI assistant
✦ ИИ-помощник|✦ AI assistant
Открыть ИИ-помощника|Open AI assistant
Локальный чат на сервере Backup и личная история диалогов.|Local chat on the Backup server with private conversation history.
Проблемы серверов, изменения состояния и события портала.|Server issues, status changes, and portal events.
Настройки хранения|Retention settings
Срок хранения истории; доступ только суперадминистратору.|History retention settings for superadmins.
Состояние фонового расчёта и ручной пересчёт по датам.|Background calculation status and manual recalculation by date.
Создание учётных записей, доступ и управление пользователями.|Create accounts and manage user access.
Текущие сеансы, архив и неудачные попытки входа.|Active sessions, session history, and failed sign-ins.
← Все серверы|← All servers
← Обзор серверов|← Server overview
← Администрирование|← Administration
← Обзор|← Overview
← Сервер|← Server
← Серверы|← Servers
ПОДКЛЮЧЕНИЯ|CONNECTIONS
Регистрация компьютеров и управление доступом|Computer registration and access management
Имя агента|Agent name
Индивидуальный ключ|Agent key
Создать и получить ключ|Create and get key
Новый ключ агента|New agent key
Важный|Important
Активный|Active
Не активный|Inactive
Не активные|Inactive servers
Важный — уведомления о проблемах. Активный — в основном списке. Флажки сохраняются сразу.|Important agents send issue alerts. Active agents appear in the main list. Changes save immediately.
Перевыпустить ключ|Rotate key
Удалить агента и историю|Delete agent and history
Для подтверждения введите имя агента|Enter the agent name to confirm
Пользователь|Viewer
Администратор|Administrator
Суперадмин|Superadmin
Суперадминистратор|Superadmin
Только суперадминистратор|Superadmins only
Пароль (от 12 символов)|Password (at least 12 characters)
Новый пароль|New password
Изменить пароль|Change password
Сменить пароль и завершить сеансы|Change password and end sessions
Отключить учётную запись|Disable account
Включить учётную запись|Enable account
Удалить пользователя|Delete user
Сохранить доступ|Save access
Для подтверждения введите логин|Enter the username to confirm
Снять блокировку входа|Unblock sign-in
Снять блокировку IP|Unblock IP
Учётные записи|Accounts
Логин не указан|No username provided
Вход заблокирован|Sign-in blocked
Неудачный вход|Failed sign-in
страна неизвестна|country unknown
неизвестен|unknown
Последняя активность:|Last activity:
Истекает:|Expires:
Завершение:|Ended:
Попытка:|Attempt:
Вход:|Sign-in:
Данные браузера|Browser details
Записей пока нет.|No records yet.
История мониторинга|Monitoring history
Хранить записи, дней|Keep records for, days
Сохранить срок хранения|Save retention period
Как работает хранение|How retention works
При уменьшении срока подтверждаю удаление более старых записей при следующей очистке|I confirm that older records will be removed during the next cleanup if I shorten retention
Обновить состояние|Refresh status
В работе|In progress
Следующая дата|Next date
Последний завершённый расчёт|Last completed calculation
Каждый день после 01:00 МСК рассчитываются завершённые сутки. Пересчёт выполняется в фоне.|Completed days are calculated daily after 01:00 Moscow time, in the background.
Диски с риском заполнения|Disks at risk of filling
Подтверждённых прогнозов заполнения на эту неделю нет.|No disk is forecast to fill up this week.
Загружаем прогнозы…|Loading forecasts…
Открыть прогнозы|Open forecasts
Не удалось загрузить прогнозы.|Could not load forecasts.
Бэкапы требуют проверки|Backups need attention
В свежих отчётах проблем с файлами копий нет.|The latest reports show no backup file issues.
Повторяющиеся сбои|Recurring incidents
Повторяющихся инцидентов за неделю нет.|No recurring incidents this week.
Серверы без свежих данных|Servers without recent data
Отчётов пока нет|No reports yet
Неизвестный период|Unknown period
Сутки|24 hours
Месяц|Month
Активные проблемы|Active issues
Завершённые инциденты|Resolved incidents
Восстановлено|Recovered
Продолжается|Ongoing
Начало|Started
Окончание|Ended
Длительность|Duration
Проблема|Issue
Последний файл|Last file
Расписание|Schedule
Ежедневно|Daily
Ежемесячно|Monthly
Копия ожидается к|Backup due by
Просрочка|Overdue
Просрочка по последней проверке|Overdue at last check
Файл обнаружен|File found
Файл не найден|File not found
Проверка восстановления|Restore verification
Данных нет|No data
Данные устарели|Stale data
Данные устарели — нет связи с агентом|Stale data — agent offline
Проверяем стабильность|Checking file stability
Ошибка бэкапа|Backup error
Ошибка чтения|Read error
Не работает|Stopped
Работает|Running
Имя и цепочка подтверждены|Hostname and certificate chain verified
Неожиданный HTTP-код|Unexpected HTTP status
Предупреждать о TLS за, дней|Warn before TLS expiry, days
Последняя проверка:|Last check:
Результат проверки устарел.|The check result is stale.
Источник не настроен|Source not configured
Источник недоступен|Source unavailable
Снимок устарел|Snapshot is stale
Найден в снимке|Listed in snapshot
Не найден в снимке|Not listed in snapshot
Состав группы|Group membership
Изменить состав|Edit membership
Порядок|Order
Снять выбор найденных|Clear matching entries
Выбрать найденные|Select matching entries
Узел|Host
Порт|Port
Дисковое пространство|Disk space
Свободно|Free
Занято|Used
Всего памяти|Total memory
Время работы|Uptime
Автообновление|Auto-refresh
Снять выбор|Clear selection
× Снять выбор|× Clear selection
⌖ Выбранное измерение|⌖ Selected measurement
▣ Снимок сервера|▣ Server snapshot
↗ Исходные отчёты|↗ Raw reports
Открыть полный снимок выбранного отчёта|Open the full snapshot for this report
Открыть точные отчёты|Open original reports
Снимок отчёта|Report snapshot
Нет полученных измерений|No measurements received
Нет измерений за выбранный период.|No measurements for this period.
Рядом нет полученных измерений|No measurements nearby
Разрывы — нет данных|Gaps indicate missing data
Высокая загрузка CPU|High CPU usage
Мало свободной RAM|Low available RAM
Нет связи с агентом|Agent offline
Фоновые задачи|Background jobs
Службы и таймеры systemd|systemd services and timers
Нет зарегистрированных копий. Внешние резервные копии здесь не учитываются.|No registered backups. External backups are excluded.
Отметок выполнения пока нет. Они появятся после работы обновлённых задач.|No runs recorded yet. Updated jobs will report here after running.
Состояние systemd недоступно в этой среде.|systemd status is unavailable in this environment.
Компонент|Component
Наблюдаемое состояние|Observed status
Результат / последний запуск|Result / last run
Проверка резервной копии|Backup verification
База данных|Database
Чтение SQLite работает|SQLite is readable
Техническая информация о базе|Database details
Время проверок и диагностика|Check times and diagnostics
Статус серверов|Server status
За сутки|Daily
Без данных|Missing data
CPU ср. / пик|CPU avg / peak
RAM ср. / пик|RAM avg / peak
Изменение CPU / RAM³|CPU / RAM change³
Перезагрузки¹|Restarts¹
Началось / завершилось инцидентов|Incidents opened / resolved
Изменения комплектации²|Hardware changes²
Серверы · до 6|Servers · up to 6
Сравнить|Compare
В этой группе пока нет серверов.|This group has no servers yet.
Новая группа|New group
Создать|Create
Найти сервер|Find server
Сохранить состав|Save membership
Удалить группу|Delete group
Период|Period
Показатель|Metric
По вашему запросу серверы не найдены.|No servers match your search.
Сначала добавьте серверы в разделе «Управление агентами».|First add servers under Agent management.
Дата (МСК)|Date (Moscow time)
Информация|Information
Событий по выбранным условиям нет.|No events match these filters.
Более ранние события →|Earlier events →
Уровень|Level
Все|All
Категория|Category
Все категории|All categories
Обновление агентов|Update agents
Обновление перезапускает только службу агента. Перезагрузка ОС и установка драйверов запрещены.|Updates restart only the agent service. OS reboots and driver installation are prohibited.
Массовые действия и доступные версии|Bulk actions and available versions
Отмена заданий|Cancel jobs
Отменить все ожидающие обновления|Cancel all queued updates
Обновить все агенты|Update all agents
Разрешаю короткий перезапуск служб агентов|Allow a brief restart of the agent services
Разрешаю короткий перезапуск службы агента|Allow a brief restart of the agent service
Проверяем GitHub и создаём задачи…|Checking GitHub and queuing jobs…
Доступные версии|Available versions
Нажмите, чтобы получить новые сборки из GitHub.|Select to fetch newer builds from GitHub.
Проверить GitHub|Check GitHub
Найти агента|Find agent
Сервер / текущая версия|Server / installed version
Состояние обновления|Update status
Обновление выполняется|Update in progress
Текущая версия:|Installed version:
История обновлений|Update history
История обновлений пока пуста.|No updates in the history yet.
Массовое обновление|Bulk update
Нет свежего отчёта|No recent report
Текущий этап:|Current stage:
Перейти на версию|Switch to version
Установить выбранную версию|Install selected version
Время (МСК)|Time (Moscow time)
Этап|Stage
Автоматически контролировать обнаруженные службы 1С и SQL Server|Automatically monitor detected 1C and SQL Server services
Правила бэкапов|Backup rules
Правило бэкапа|Backup rule
Добавить папку|Add folder
Изменений нет|No changes
Сохранить и передать агенту|Save and send to agent
Подтверждаю возврат к локальным настройкам|I confirm switching back to local settings
Использовать локальные настройки|Use local settings
Каждое 1-е число|First day of each month
Удалить это правило|Remove this rule
← Управление агентами|← Agent management
МОНИТОРИНГ|MONITORING
Вернуться к локальному файлу|Return to local configuration
Агент снова использует папки и службы из своего config.json.|The agent will use the folders and services from its local config.json again.
Службы Windows / Linux|Windows / Linux services
Обновления и перезагрузка Windows|Windows updates and restart
Последние записи установок Windows Update|Recent Windows Update installations
Системные исправления (KB)|System updates (KB)
Получаем сведения Windows…|Loading Windows details…
История Windows Update недоступна.|Windows Update history is unavailable.
Список системных исправлений недоступен.|The list of system updates is unavailable.
История пуста или очищена.|The history is empty or has been cleared.
Системные исправления не найдены.|No system updates found.
Контроль портала →|Portal health →
Raspberry Pi — портал|Raspberry Pi — portal host
Мониторинг хоста ещё не подключён|Host monitoring is not set up
Данных о ресурсах машины портала пока нет.|No resource data for the portal host yet.
Как подключить мониторинг|Set up monitoring
Диски, службы и состояние →|Disks, services, and status →
Графики CPU, ОЗУ, сети и дисков →|CPU, memory, network, and disk charts →
Сейчас|Now
Отчёты задерживаются|Reports delayed
Графики нагрузки|Resource charts
Открыть сервер →|Open server →
По ядрам · логические процессоры|Per core · logical processors
По ядрам|Per core
логические процессоры|logical processors
частота ОС|OS-reported frequency
занято / всего|used / total
Доступность за 24 ч:|24-hour uptime:
В работе:|Uptime:
Нет измерений CPU и RAM рядом|No nearby CPU or RAM measurements
Посещаемость портала|Portal traffic
Визитка, переходы в панель, источники и попытки входа.|Landing page, panel visits, referral sources, and sign-in attempts.
Просмотры визитки|Landing page views
Открытия формы входа|Sign-in form opens
Открытия панели|Dashboard opens
Успешные входы|Successful sign-ins
Отклонено блокировкой|Blocked sign-ins
Переходы к примеру|Demo clicks
Переходы к описанию|How it works clicks
Сеансы портала →|Portal sessions →
24 часа|24 hours
7 дней|7 days
90 дней|90 days
IP-адрес|IP address
Событие|Event
Все события|All events
Применить|Apply
Уникальные IP визитки|Unique landing page IPs
Частые IP визитки|Top landing page IPs
Нет данных за период|No data for this period
Источники визитки|Landing page sources
Источник не передан|Source unavailable
Журнал посещений и входов|Traffic and sign-in log
Время|Time
Страна|Country
Источник|Source
Подробнее|Details
← Назад|← Previous
Далее →|Next →
Новые события навигации записываются после обновления. Один IP могут использовать несколько человек. Страна показывается при наличии базы IP-геолокации.|New navigation events are recorded after the update. Multiple people can share an IP address. Country is shown when an IP geolocation database is available.
Настройки Telegram|Telegram settings
Настройки сохранены.|Settings saved.
Перезапустить бота|Restart bot
Состояние бота|Bot status
Запрос отправлен. Ожидаем ответа от бота.|Restart requested. Waiting for the bot to respond.
Бот принял запрос. Ожидаем запуска нового процесса.|The bot accepted the request. Waiting for the new process to start.
Бот не подтвердил перезапуск. Проверьте, что служба запущена и обновлена.|The bot did not acknowledge the restart. Check that the service is running and up to date.
Бот принял запрос, но новый процесс не подтвердил запуск. Проверьте журнал службы.|The bot accepted the request, but the new process did not confirm startup. Check the service log.
Бот перезапустился. Ожидаем подключения к Telegram.|The bot restarted. Waiting for Telegram connectivity.
Бот перезапустился и подключился к Telegram.|The bot restarted and connected to Telegram.
Бот перезапустился, но пока не подключился к Telegram.|The bot restarted but has yet to connect to Telegram.
Проверьте формат токена и ID чата.|Check the token and chat ID format.
Подтвердите замену токена перед сохранением.|Confirm the token replacement before saving.
Укажите числовой Telegram ID и имя длиной до 80 символов.|Enter a numeric Telegram ID and a name of up to 80 characters.
Достигнут предел списка пользователей Telegram.|The Telegram user list has reached its limit.
Этот Telegram ID уже есть в списке. Измените существующую запись.|This Telegram ID is already listed. Edit the existing entry.
Сначала настройте токен и чат уведомлений.|Set up the bot token and notifications chat first.
Не удалось сохранить настройки Telegram.|Could not save Telegram settings.
Имя в портале|Name in the portal
Администратор бота|Bot administrator
Заблокирован|Blocked
Исходное имя появится после первого сообщения, которое бот получит от пользователя.|The original name appears after the bot receives its first message from the user.
Пока список пользователей отчётов пуст, команды доступны участникам чата уведомлений.|While the reporting user list is empty, members of the notifications chat can run report commands.
Заблокированный пользователь не сможет пользоваться ботом или получать личные сообщения. Чтобы скрыть уведомления общего чата, удалите пользователя из этого чата в Telegram.|Blocked users cannot use the bot or receive direct messages. To hide shared notifications from a user, remove them from the Telegram chat.
Имя пока неизвестно|Name not yet known
После замены токена старый бот перестанет обслуживать портал. Вы уверены?|Replacing the token will disconnect the old bot from the portal. Are you sure?
Подтверждаю замену токена|Confirm token replacement
Сохранить настройки|Save settings
Ожидающих ответов:|Pending replies:
Время проверок и диагностика|Check times and diagnostics
Состояние процесса|Process heartbeat
Последний успешный опрос Telegram|Last successful Telegram poll
Последний ответ на команду|Last command reply
ещё нет данных|No data yet
Ошибка отправки ответа. Проверьте доступ бота к чату.|Could not send a reply. Check the bot's access to the chat.
Состояние обновляется автоматически. В Telegram отправьте /start, чтобы показать кнопки. Запросы по кнопкам доступны круглосуточно.|Status refreshes automatically. Send /start in Telegram to show the buttons. Commands are available around the clock.
Процесс работает, но соединение с Telegram недоступно|The bot is running but cannot connect to Telegram
Процесс работает, но ответ в Telegram не доставлен|The bot is running but Telegram did not receive a reply
Процесс работает, успешный опрос Telegram пока не подтверждён|The bot is running but has not successfully polled Telegram
Токен настроен|Token configured
Токен не задан|Token missing
Новый токен бота|New bot token
Оставьте токен пустым, чтобы сохранить текущий.|Leave the token blank to keep the current one.
ID чата уведомлений|Notifications chat ID
Доступ пользователей Telegram|Telegram user access
Администратор портала|Portal administrator
Пользователь отчётов|Reporting user
Бот ещё не запущен|Bot has not started
Бот работает|Bot is running
Нет свежего состояния процесса бота|Bot status is stale
Подключается к Telegram|Connecting to Telegram
Подключение локального ИИ|Local AI connection
Состояние подключения и инструкция по настройке.|Connection status and setup instructions.
Локальная модель доступна|Local model is available
Локальная модель не подключена|Local model is disconnected
Ответы генерирует локальная модель на вашем сервере. Веб-токен облачного ИИ для этого не используется.|Answers are generated by the local model on your server. No cloud AI web token is used.
Установите локальную модель и обратный SSH-туннель на сервере Backup по инструкции deploy/AI-CONNECTION.md.|Set up the local model and reverse SSH tunnel on Backup using deploy/AI-CONNECTION.md.
На сервере портала запустите настройку ключа локальной модели.|Start local-model key setup on the portal host.
Введите ключ в терминале по запросу скрипта. Портал проверяет локальное подключение в фоне. Когда модель доступна, кнопка чата появляется в панели.|Enter the key in the terminal when prompted. The portal checks connectivity in the background and shows the chat button when the model is available.
Подключение…|Connecting…
Загрузка чата…|Loading chat…
ЛОКАЛЬНАЯ МОДЕЛЬ · BACKUP|LOCAL MODEL · BACKUP
Ваши вопросы обрабатываются на вашем сервере.|Your questions are processed on your server.
Диалог|Conversation
Новый диалог|New conversation
＋ Новый|＋ New
Чем помочь?|How can I help?
Интернет|Internet
Ваш вопрос|Your question
Напишите вопрос…|Enter a question…
Отправить ↑|Send ↑
■ Остановить|■ Stop
`.trim().split('\n').map(line=>line.split('|')));
  const patterns=[
    [/^Показано (\d+) из (\d+)$/u,'Showing $1 of $2'],
    [/^Заполненность дисков · (.+)$/u,'Disk usage · $1'],
    [/^Отмечено «Всё окей»: (\d+)$/u,'Acknowledged: $1'],
    [/^(\d+)[\u00a0 ]мс$/u,'$1 ms'],
    [/^Готово дней: (\d+) · В очереди: (\d+)$/u,'Days ready: $1 · Queued: $2'],
    [/^Свободно (.+)$/u,'Free: $1'],
    [/^(.+) свободно$/u,'$1 free'],
    [/^(.+) занято$/u,'$1 used'],
    [/^Не отвечает приложение: (.+)$/u,'Application not responding: $1'],
    [/^Служба не работает: (.+)$/u,'Service stopped: $1'],
    [/^Заполнен диск (.+)$/u,'Disk filling up: $1'],
    [/^Ошибка бэкапа: (.+)$/u,'Backup issue: $1'],
    [/^Ожидающих ответов: (\d+)$/u,'Queued replies: $1'],
    [/^Отчёт: (.+)$/u,'Report: $1'],
    [/^В работе: (.+)$/u,'Uptime: $1'],
    [/^● (.+)$/u,'● $1'],
    [/^Доступность за (\d+) ч:$/u,'$1-hour uptime:'],
    [/^Процесс работает, но соединение с Telegram недоступно$/u,'Bot is running, but Telegram is unreachable'],
    [/^Процесс работает, но ответ в Telegram не доставлен$/u,'Bot is running, but the reply was not delivered'],
  ];
  const root=document.documentElement;
  const originals=new WeakMap();
  const attributes=['aria-label','title','placeholder'];
  const excluded='script,style,pre,code,textarea,[data-no-translate]';
  let language='ru';

  function translated(value) {
    if(language==='ru')return value;
    const plain=value.trim().replace(/\s+/g,' ');
    const result=translateLabel(plain);
    return result===plain ? value : value.match(/^\s*/)[0]+result+value.match(/\s*$/)[0];
  }

  function translateLabel(plain) {
    const direct=translations.get(plain);
    if(direct)return direct;
    if(plain.includes(' · '))return plain.split(' · ').map(translateLabel).join(' · ');
    if(plain.startsWith('● '))return '● '+translateLabel(plain.slice(2));
    let result=plain;
    for(const [pattern,replacement] of patterns){
      if(pattern.test(plain)){result=plain.replace(pattern,replacement);break}
    }
    const units={'с':'s','мин':'min','ч':'h','д':'d','Б':'B','Кб':'KB','Мб':'MB','Гб':'GB','Тб':'TB','ГГц':'GHz','МГц':'MHz','п.п.':'pp'};
    return result.replace(/(\d)\s+(п\.п\.|ГГц|МГц|Кб|Мб|Гб|Тб|мин|Б|д|ч|с)(?=\s|[)/,.]|$)/gu,(_m,digit,unit)=>digit+' '+units[unit])
      .replace(/(\d (?:s|min|h|d)) назад$/u,'$1 ago');
  }

  function update(node,slot,value,write) {
    let record=originals.get(node);
    if(!record){record={};originals.set(node,record)}
    const previous=record[slot];
    const source=previous?.applied===value?previous.source:value;
    const next=translated(source);
    record[slot]={source,applied:next};
    if(next!==value)write(next);
  }

  function visit(node) {
    if(node.nodeType===3){
      const parent=node.parentElement;
      if(!parent||parent.closest(excluded)||!node.data.trim())return;
      if(parent.tagName==='OPTION'&&!parent.hasAttribute('value'))parent.value=parent.textContent;
      update(node,'text',node.data,value=>{node.data=value});
    }else if(node.nodeType===1&&!node.closest(excluded)){
      for(const attribute of attributes){
        if(node.hasAttribute(attribute))update(node,attribute,node.getAttribute(attribute),value=>node.setAttribute(attribute,value));
      }
      for(const child of node.childNodes)visit(child);
    }
  }

  function apply(choice) {
    language=choice==='en'?'en':'ru';
    root.lang=language;
    for(const control of document.querySelectorAll('[data-language-choice]')){
      const label=language==='en'?'ENG':'RUS';
      const caption=control.querySelector('[data-language-label]');
      if(caption&&caption.textContent!==label)caption.textContent=label;
      control.setAttribute('aria-label',language==='en'?'Переключить на русский':'Switch to English');
    }
    visit(document.body);
  }

  let choice;
  try{choice=localStorage.getItem(key)}catch(_){}
  apply(choice);
  const observer=new MutationObserver(records=>{
    if(language==='ru')return;
    for(const record of records){
      if(record.type==='characterData')visit(record.target);
      else if(record.type==='attributes'){
        const attr=record.attributeName,node=record.target;
        if(!node.closest(excluded)&&node.hasAttribute(attr))update(node,attr,node.getAttribute(attr),value=>node.setAttribute(attr,value));
      }else for(const node of record.addedNodes)visit(node);
    }
  });
  observer.observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:attributes});
  document.addEventListener('click',event=>{
    if(!event.target.closest('[data-language-choice]'))return;
    apply(language==='ru'?'en':'ru');
    try{localStorage.setItem(key,language)}catch(_){}
  });
  window.addEventListener('storage',event=>{if(event.key===key||event.key===null)apply(event.newValue)});
})();
