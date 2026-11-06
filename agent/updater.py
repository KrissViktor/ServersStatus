"""Update an existing standard installation without touching its configuration."""
from datetime import datetime
from pathlib import Path
import shutil
import time


def wait(command, state):
    script = "(Get-Service -Name 'ServersStatusAgent').WaitForStatus('" + state + "', [TimeSpan]::FromSeconds(60))"
    command('powershell.exe', '-NoProfile', '-NonInteractive', '-Command', "$ErrorActionPreference='Stop'; " + script)


def stop(command):
    result = command('sc.exe', 'stop', 'ServersStatusAgent', check=False)
    if result.returncode not in (0, 1062):
        raise RuntimeError('Не удалось остановить службу: ' + (result.stderr or result.stdout))
    wait(command, 'Stopped')


def update_service(command, root, bundled_executable):
    executable = Path(root) / 'ServersStatusService.exe'
    source = Path(bundled_executable)
    if not executable.is_file():
        raise ValueError('Не найдена установленная EXE-служба. Для первой установки заполните поля и нажмите «Установить».')
    if not source.is_file():
        raise ValueError('В установщике отсутствует EXE службы. Скачайте полную сборку.')
    if command('sc.exe', 'query', 'ServersStatusAgent', check=False).returncode:
        raise ValueError('Служба не зарегистрирована. Выполните установку агента.')
    backup = executable.with_name(executable.name + '.' + datetime.now().strftime('%Y%m%d%H%M%S%f') + '.previous')
    stop(command)
    try:
        shutil.copy2(executable, backup)
        shutil.copy2(source, executable)
        command('sc.exe', 'start', 'ServersStatusAgent')
        wait(command, 'Running')
        time.sleep(2)
        command('powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                "if ((Get-Service ServersStatusAgent).Status -ne 'Running') { exit 1 }")
    except Exception as error:
        try:
            stop(command)
            if backup.exists():
                shutil.copy2(backup, executable)
            command('sc.exe', 'start', 'ServersStatusAgent')
            wait(command, 'Running')
        except Exception as rollback_error:
            raise RuntimeError('Обновление не удалось, автоматическое восстановление тоже. Резервная копия: ' + str(backup) + '. Ошибка восстановления: ' + str(rollback_error)) from error
        raise RuntimeError('Обновление не удалось. Предыдущий EXE восстановлен, служба запущена. Причина: ' + str(error)) from error
    return backup
