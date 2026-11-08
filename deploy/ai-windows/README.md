# Локальная модель — windows-02 / WIN-CU629F0N7II

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
  Агент `windows-02`, его конфигурация и ключ не используются и не меняются.
- Оболочка LocalService, автозапуск, SCM recovery после сбоев. У пользователя
  службы только чтение кода/модели/настроек и запись в каталог логов.

Настройки: CPU максимум 80% общего процессорного времени (Job Object hard cap),
BelowNormal priority, до 22 Гб **committed memory** дочернего процесса/задания,
без mmap, 16 потоков, один запрос, контекст 8192, максимум 512 новых токенов,
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

Установщик рассчитан на `WIN-CU629F0N7II`. На другом ПК он остановится;
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
Если latest содержит только nightly-tag.txt (например v0.9.0), установщик
следует официальному указателю на бинарную сборку, затем проверяет её digest.
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

Если старая версия установщика сообщает `Could not identify exactly one official
Windows CPU x64 ZIP`, можно явно указать проверенный бинарный тег:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\ServersStatusAISetup\ServersStatus-main\deploy\ai-windows\Install-AI.ps1' -EngineTag b12110
```

Либо обновите исходники установщика из main — автоматическое разрешение
stable → nightly исправлено. Привязка к Windows CPU x64 и проверка SHA256
сохраняются; ARM/CUDA/OpenVINO-сборки автоматически не выбираются.

### EXE не запускается: 0xC0000135 / -1073741515

Это код отсутствующей DLL, часто Microsoft VC++ Runtime x64. Установите
официальный пакет https://aka.ms/vs/17/release/vc_redist.x64.exe, затем проверьте
`llama-server.exe --help` повторно. Если код сохраняется, проверьте DLL рядом
с EXE и Windows Application Event Log; один код не называет конкретную DLL.
Установщик не считает такую ошибку проблемой GGUF.

Новый установщик проверяет EXE **до** загрузки модели. Диагностика с точным
decimal/hex exit code, stdout/stderr сохраняется в
`C:\ProgramData\ServersStatusAI\logs\engine-check.log`.

При повторном запуске engine.zip и однофайловая model.gguf используются из
кэша только после сверки SHA256 с официальными метаданными. Уже загруженные
части тоже проверяются и используются повторно. Повреждённый/другой файл
скачивается заново; незавершённый .part не принимается за проверенную модель.
Для повторного запуска больше не требуется ещё 30 Гб свободно, если файлы
уже есть: свободное место проверяется перед недостающей загрузкой/копией/слиянием.


## CPU 80% и 16 потоков без переустановки

Выполнять на **Backup / WIN-CU629F0N7II**, PowerShell от администратора:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/KrissViktor/ServersStatus/main/deploy/ai-windows/Update-AIResources.ps1' -OutFile 'C:\ProgramData\ServersStatusAI\Update-AIResources.ps1'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\ProgramData\ServersStatusAI\Update-AIResources.ps1'
```

Скрипт фиксирует CpuPercent=80 и --threads/--threads-batch=16, сохраняет резервную
копию XML и перезапускает только работающую службу ServersStatusAI. Модель
перезагрузится; дождитесь загрузки. Служба, остановленная ранее, сама не включается.
При сбое запуска восстанавливается предыдущий XML и предпринимается запуск службы.
Повторное применение не перезапускает уже настроенную службу. Модель/движок не
скачиваются, память 22 Гб + резерв 4 Гб, ключи и SSH-туннель не меняются.

В исходной конфигурации потолок CPU уже 80%, но раньше было 12 потоков. На i7-12700K
20 логических процессоров; 12 активных потоков могут давать около 60% суммарной
загрузки. Это возможная причина, не измерение вашей машины. 80% — максимальная
доля CPU, а не целевая загрузка. Большее число потоков не гарантирует ускорения:
генерация может ограничиваться пропускной способностью памяти. Сравнивайте
скорость в Test-AI.ps1 до/после. Число потоков можно вернуть без переустановки:
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\ProgramData\ServersStatusAI\Update-AIResources.ps1 -Threads 12`.
