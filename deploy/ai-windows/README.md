# Локальная модель — windows-04 / WIN-4JJ50EC22U2

Первый этап: запустить и измерить локальный сервер модели на Windows Server
2022 x64, i7-12700K, без отдельной видеокарты. Портал и агент не изменяются.
Чат в портале, защищённая связь с Raspi, интернет-поиск и интеграция 1С — следующие
этапы, здесь они ещё не реализованы. Модель сама интернет не просматривает.

## Что устанавливается

- Официальный CPU ZIP llama.cpp из GitHub Releases. Версия фиксируется в
  `versions.json`; архив сверяется с SHA256 из официального asset digest.
- Qwen3-14B Q4_K_M GGUF из официального `Qwen/Qwen3-14B-GGUF`. Ревизия
  закрепляется commit SHA метаданных, файлы сверяются с LFS SHA256. Разбитая модель скачивается всеми частями,
  каждая проверяется, затем штатный llama-gguf-split объединяет GGUF.
- C#/.NET Framework служба `ServersStatusAI`, компилируется встроенным Windows
  `csc.exe`; отдельный Python, Docker и SDK устанавливать не нужно.
- Каталог `C:\ProgramData\ServersStatusAI`, отдельный случайный API-ключ.
  Агент `windows-04`, его конфигурация и ключ не используются и не меняются.
- Оболочка LocalService, автозапуск, SCM recovery после сбоев. У пользователя
  службы только чтение кода/модели/настроек и запись в каталог логов.

Настройки: CPU максимум 80% общего процессорного времени (Job Object hard cap),
BelowNormal priority, до 22 Гб **committed memory** дочернего процесса/задания,
без mmap, 12 потоков, один запрос, контекст 8192, максимум 512 новых токенов,
thinking отключён. Это потолки, а не постоянное резервирование/загрузка.
ОС, файловый кэш и память других программ не входят в лимит задания.

При старте нужны не менее 26 Гб свободной физической памяти (22 + резерв 4).
При работе, если свободно менее 4 Гб, модель выгружается. Автозапуск возобновится,
когда снова будет достаточно памяти. В журнале будет `Waiting for free RAM`.
Если модель завершается/превышает лимит задания, SCM перезапускает службу с
задержкой. Реальную скорость токенов/с и потребление надо измерить на сервере;
проверка службы в CI не является проверкой производительности модели.

## Установить на Windows

Нужно: PowerShell **от администратора**, .NET Framework 4.8 (штатно в Server
2022), интернет к GitHub/Hugging Face и их CDN, не менее 30 Гб свободно на C:
для частей модели, объединённого GGUF и движка. Большие загрузки могут идти долго.

Сначала скачать исходники проекта (это не скачивает модель):

```powershell
$dest = 'C:\ServersStatusAISetup'
New-Item -ItemType Directory -Force -Path $dest | Out-Null
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/KrissViktor/ServersStatus/archive/refs/heads/main.zip' -OutFile "$dest\source.zip"
Expand-Archive -LiteralPath "$dest\source.zip" -DestinationPath $dest -Force
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$dest\ServersStatus-main\deploy\ai-windows\Install-AI.ps1"
```

Установщик рассчитан на `WIN-4JJ50EC22U2`. На другом ПК он остановится;
`-AllowOtherComputer` нужен только при осознанной установке на другой сервер.
Не запускайте установщик повторно поверх уже установленной службы.

Если доступ к Hugging Face отсутствует или официальный формат сборки не
поддерживается, установщик остановится с пояснением. Можно самостоятельно
получить совместимый однофайловый Qwen3 GGUF и его SHA256 из доверенного источника:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\ServersStatusAISetup\ServersStatus-main\deploy\ai-windows\Install-AI.ps1' -ModelPath 'D:\Models\model.gguf' -ModelSha256 '<64 hex символа SHA256>'
```

Служба появляется только после загрузки и проверок. Неуспешная загрузка не
заменяет агент и не создаёт правил брандмауэра. `EngineTag` позволяет выбрать
конкретный релиз вместо latest; релиз без опубликованного digest отклоняется.
Если запуск сообщает об отсутствующем VC++ runtime, установите официальный
Microsoft Visual C++ Redistributable x64: https://aka.ms/vs/17/release/vc_redist.x64.exe
и повторите запуск службы. Установщик не отключает Defender/проверку TLS.

## Проверить

После нескольких минут загрузки:

```powershell
Get-Service ServersStatusAI
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\ProgramData\ServersStatusAI\Test-AI.ps1'
Get-Content 'C:\ProgramData\ServersStatusAI\logs\service.log' -Encoding UTF8 -Tail 40
```

Test-AI читает ключ локально, отправляет короткий вопрос, показывает ответ,
длительность и доступные счётчики. Первый запрос включает прогрев; сделайте
2–3 запроса и сравните скорость. Если 14B слишком медленна, следующим шагом
подготовим 8B с тем же API. Не присылайте `api-key.txt` в чат.

API: `http://127.0.0.1:8091/v1/chat/completions`, модель `serversstatus-local`.
Он слушает **только loopback**, защищён ключом. Наружу порт не пробрасывается,
правил брандмауэра установщик не добавляет. Доступа из Raspi пока нет: следующим
шагом настроим туннель/relay с проверкой ключа, затем чат с существующими ролями.

## Бэкапы и обслуживание

Перед бэкапом (за несколько секунд) можно выгрузить модель:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\ProgramData\ServersStatusAI\Pause-AI.ps1' -Minutes 120
```

Это создаёт маркер, служба выгружает процесс максимум через несколько секунд;
активный ответ прерывается. Проверьте сообщение `Paused for backup/maintenance`
в логе. После бэкапа:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\ProgramData\ServersStatusAI\Resume-AI.ps1'
```

Или пауза закончится автоматически по времени. **Автоматическое обнаружение
вашей программы бэкапов не подключено**: нужны её процесс/команда либо вставка
Pause/Resume в существующий сценарий с try/finally. Не угадываем активность SQL
по одному наличию процесса. До привязки запускайте паузу сами перед бэкапами.

Отключить полностью: `Stop-Service ServersStatusAI`.
Удалить службу, сохранив модель/настройки/ключ/логи:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\ProgramData\ServersStatusAI\Uninstall-AI.ps1'
```

Логи ограничены двумя файлами примерно по 20 Мб. Служебные файлы с секретами
доступны администраторам/SYSTEM/LocalService. Загруженные EXE/GGUF, ключи,
локальные пути и XML-настройки не добавляются в Git.

## Изменить резерв уже установленной службы

Чтобы снизить порог с 28 до 26 Гб без повторной установки (при лимите модели
22 Гб), выполните в PowerShell от администратора:

```powershell
$path = 'C:\ProgramData\ServersStatusAI\settings.xml'
[xml]$settings = Get-Content -LiteralPath $path -Raw
$settings.Settings.ReserveMB = '4096'
Stop-Service ServersStatusAI
$settings.Save($path)
Start-Service ServersStatusAI
```

Лимит памяти модели, ключ и файлы остаются прежними. После перезапуска модель
ожидает 26 Гб свободно; при работе выгружается, если свободно меньше 4 Гб.
