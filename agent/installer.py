"""Elevated graphical installer bundled with the standalone service executable."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox
from urllib.parse import urlsplit, quote
import urllib.request

ROOT = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'ServersStatus'
DATA = Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'ServersStatus'


def command(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)


def install():
    button.config(state='disabled')
    window.update()
    try:
        url, name, key = [entry.get().strip() for entry in entries]
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('Укажите HTTPS-адрес панели без пути и параметров.')
        if not name or not key or '/' in name or '\\' in name:
            raise ValueError('Укажите имя агента и ключ. Имя не должно содержать слеши.')
        status.set('Проверка подключения…')
        window.update()
        payload = {'hostname': os.environ.get('COMPUTERNAME', name), 'cpu_percent': 0, 'memory_percent': 0, 'uptime_seconds': 0, 'disks': [], 'backups': [], 'services': []}
        request = urllib.request.Request(url.rstrip('/') + '/api/report/' + quote(name, safe=''), data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 200:
                raise ValueError('Панель не приняла отчёт.')
        status.set('Установка службы…')
        window.update()
        ROOT.mkdir(parents=True, exist_ok=True)
        DATA.mkdir(parents=True, exist_ok=True)
        # Restrict before writing the agent key; use SIDs for localized Windows.
        command('icacls', str(DATA), '/inheritance:r', '/grant:r', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F')
        query = command('sc.exe', 'query', 'ServersStatusAgent', check=False)
        if query.returncode == 0:
            raise ValueError('Служба уже установлена. Для обновления сначала остановите и удалите её по инструкции README. Текущие настройки сохранены.')
        config_path = DATA / 'config.json'
        config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
        config.update(server_url=url.rstrip('/'), agent_id=name, token=key)
        config.setdefault('interval_seconds', 60)
        config.setdefault('services', [])
        config.setdefault('backups', [])
        temporary = DATA / 'config.new'
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(config_path)
        executable = ROOT / 'ServersStatusService.exe'
        shutil.copy2(Path(sys._MEIPASS) / 'ServersStatusService.exe', executable)
        command(str(executable), '--startup', 'auto', 'install')
        command('sc.exe', 'failure', 'ServersStatusAgent', 'reset=', '86400', 'actions=', 'restart/10000/restart/30000/restart/60000')
        command(str(executable), 'start')
        status.set('Служба установлена. Проверьте показатели в панели через минуту.')
        messagebox.showinfo('ServersStatus', 'Служба установлена и запущена. Проверьте обновление показателей в панели через минуту.')
    except Exception as error:
        # Do not include request headers or config in errors.
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        status.set('Установка не завершена')
        messagebox.showerror('ServersStatus', detail)
    finally:
        button.config(state='normal')


if __name__ == '__main__':
    window = tk.Tk()
    window.title('Установка ServersStatus Agent')
    window.geometry('610x300')
    entries = []
    for index, (label, default) in enumerate([('Адрес панели', 'https://panel.vikserver.ru'), ('Имя агента', ''), ('Ключ агента', '')]):
        tk.Label(window, text=label).grid(row=index, column=0, padx=12, pady=12, sticky='w')
        entry = tk.Entry(window, width=52, show='*' if index == 2 else '')
        entry.insert(0, default)
        entry.grid(row=index, column=1, padx=12)
        entries.append(entry)
    button = tk.Button(window, text='Проверить подключение и установить', command=install)
    button.grid(row=3, column=0, columnspan=2, pady=15)
    status = tk.StringVar(value='Потребуются права администратора Windows.')
    tk.Label(window, textvariable=status, wraplength=570).grid(row=4, column=0, columnspan=2)
    window.mainloop()
