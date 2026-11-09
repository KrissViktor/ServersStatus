"""Bounded hardware report schema and component summary rendering."""
from typing import Annotated
from pydantic import BaseModel, Field

KINDS = {'computer': 'Компьютер', 'board': 'Материнская плата', 'bios': 'BIOS / UEFI',
         'cpu': 'Процессоры', 'memory_array': 'Слоты и предел памяти', 'memory': 'Модули оперативной памяти',
         'gpu': 'Видеокарты', 'storage': 'Физические накопители', 'network': 'Сетевые адаптеры'}
Kind = Annotated[str, Field(pattern='^(' + '|'.join(KINDS) + ')$')]
Text = Annotated[str, Field(max_length=160)]


class HardwareItem(BaseModel):
    kind: Kind
    fields: dict[Annotated[str, Field(max_length=40)], Text] = Field(max_length=8)


class HardwareInfo(BaseModel):
    status: str = Field(pattern='^(checking|available|unavailable)$')
    items: list[HardwareItem] = Field(default_factory=list, max_length=48)
    unavailable: list[Kind] = Field(default_factory=list, max_length=9)
    truncated: bool = False
    checked_at: float | None = Field(default=None, ge=0, allow_inf_nan=False)


LABELS = {'Manufacturer': 'Производитель', 'Model': 'Модель', 'SystemType': 'Тип системы',
          'TotalPhysicalMemory': 'Установленная память', 'Product': 'Модель платы', 'Version': 'Ревизия',
          'SerialNumber': 'Серийный номер', 'SMBIOSBIOSVersion': 'Версия BIOS', 'ReleaseDate': 'Дата выпуска',
          'Name': 'Название', 'SocketDesignation': 'Сокет', 'NumberOfCores': 'Ядра',
          'NumberOfLogicalProcessors': 'Потоки', 'MaxClockSpeed': 'Максимальная частота, МГц',
          'MemoryDevices': 'Количество слотов', 'MaxCapacityEx': 'Максимальная память по SMBIOS',
          'DeviceLocator': 'Слот', 'BankLabel': 'Банк', 'PartNumber': 'Модель модуля', 'Capacity': 'Объём',
          'ConfiguredClockSpeed': 'Настроенная скорость, MT/s', 'SMBIOSMemoryType': 'Тип памяти',
          'VideoProcessor': 'Графический процессор', 'DriverVersion': 'Версия драйвера',
          'CurrentHorizontalResolution': 'Разрешение: ширина', 'CurrentVerticalResolution': 'Разрешение: высота',
          'FirmwareRevision': 'Прошивка', 'Size': 'Ёмкость', 'InterfaceType': 'Интерфейс по данным Windows',
          'MediaType': 'Тип носителя по данным Windows', 'MACAddress': 'MAC-адрес', 'Speed': 'Скорость адаптера, бит/с'}


def display(key, value):
    from .dashboard import size
    try:
        number = int(value)
        if key in ('Capacity', 'Size', 'TotalPhysicalMemory'):
            return size(number) if number > 0 else 'Не сообщается'
        if key == 'MaxCapacityEx':
            return size(number * 1024) if number > 0 else 'Не сообщается'
        if key == 'SMBIOSMemoryType':
            return {20: 'DDR', 21: 'DDR2', 24: 'DDR3', 26: 'DDR4', 30: 'LPDDR4', 34: 'DDR5', 35: 'LPDDR5'}.get(number, 'Неизвестно (SMBIOS: '+str(number)+')')
        if number == 0 and key in ('ConfiguredClockSpeed', 'MaxClockSpeed', 'Speed', 'CurrentHorizontalResolution', 'CurrentVerticalResolution'):
            return 'Не сообщается'
    except (ValueError, TypeError):
        pass
    return value


def summary(data):
    from .dashboard import esc
    info = data.get('hardware')
    if not info:
        return '<div class="hardware-summary"><h4>Комплектация</h4><p class="muted">Обновите Windows-агент для сведений о комплектации.</p></div>' if (data.get('system') or {}).get('os') == 'Windows' else ''
    content = '<div class="hardware-summary"><h4>Комплектация</h4>'
    if info.get('status') == 'checking':
        return content + '<p class="muted">Собираем сведения об оборудовании. Они появятся в следующих отчётах.</p></div>'
    if info.get('status') != 'available':
        return content + '<p class="muted">Windows не предоставила сведения об оборудовании.</p></div>'
    for kind, title in KINDS.items():
        items = [item for item in info.get('items', []) if item.get('kind') == kind]
        if not items and kind not in info.get('unavailable', []):
            continue
        content += '<div class="hardware-group"><h4>' + esc(title) + '</h4>'
        for item in items:
            content += '<dl class="system-facts hardware-component">' + ''.join('<div><dt>'+esc(LABELS.get(key, key))+'</dt><dd>'+esc(display(key, value))+'</dd></div>' for key, value in item.get('fields', {}).items()) + '</dl>'
        if not items:
            content += '<p class="muted">Сведения недоступны.</p>'
        content += '</div>'
    if info.get('truncated'):
        content += '<p class="muted">Показана часть оборудования: достигнут предел размера сводки.</p>'
    from .windows_ui import stamp
    content += '<p class="muted legend">Собрано: '+esc(stamp(info.get('checked_at')))+'. Обновление раз в час. Сведения предоставлены Windows и SMBIOS; в виртуальной машине могут описывать виртуальное оборудование. Пустые поля не сообщаются производителем. Интерфейс накопителя может отражать контроллер RAID/USB; тип SSD/HDD не угадывается.</p>'
    return content + '</div>'
