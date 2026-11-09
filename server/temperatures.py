"""Available temperature sensors in current and historical reports."""
from datetime import datetime,timezone,timedelta
from typing import Annotated,Literal
from pydantic import BaseModel,Field
from .dashboard import esc

Degrees=Annotated[float,Field(ge=-100,le=200,allow_inf_nan=False)]
class Sensor(BaseModel):
    id:str=Field(min_length=1,max_length=255)
    label:str=Field(default='',max_length=255)
    device:str=Field(default='',max_length=255)
    source:str=Field(default='',max_length=80)
    component:str=Field(default='',max_length=80)
    current:Degrees|None=None
    high:Degrees|None=None
    critical:Degrees|None=None
class TemperatureInfo(BaseModel):
    status:Literal['available','unavailable','unsupported','checking']
    sampled_at:float|None=Field(default=None,ge=0,le=4102444800,allow_inf_nan=False)
    items:list[Sensor]=Field(default_factory=list,max_length=512)


def section(data,historical=False):
    temperatures=data.get('temperatures') or {};items=temperatures.get('items') or []
    content='<section><h3>Температуры <span class="count">'+str(len(items))+'</span></h3>'
    sampled=temperatures.get('sampled_at')
    if sampled is not None:
        stamp=datetime.fromtimestamp(sampled,timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M:%S МСК')
        label='Измерено' if temperatures.get('status')=='available' else 'Последняя проверка'
        content+='<p class="muted">'+label+': '+esc(stamp)+'</p>'
    if not items:
        if temperatures.get('status')=='checking':message='Датчики опрашиваются. Дождитесь следующего отчёта.'
        elif not temperatures:message='В этом снимке температурные данные не сохранялись. Текущие значения не подставляются.' if historical else 'Температурных данных пока нет. Обновите агент.'
        else:message='Доступные датчики не обнаружены или не удалось их прочитать. На Windows для CPU/GPU/памяти может потребоваться работающий LibreHardwareMonitor с WMI. ACPI-зона не означает температуру процессора.'
        return content+'<p class="muted">'+message+'</p></section>'
    content+='<div class="temperature-scroll"><table class="temperature-table"><thead><tr><th>Датчик / устройство</th><th>Температура</th><th>Пределы</th></tr></thead><tbody>'
    for sensor in items:
        current=sensor.get('current');high=sensor.get('high');critical=sensor.get('critical')
        level='danger' if current is not None and critical is not None and current>=critical else 'warning' if current is not None and high is not None and current>=high else 'neutral'
        reading=f'{current:.1f} °C' if current is not None else 'Нет данных'
        limits=' · '.join(label+f' {v:.1f} °C' for label,v in [('Высокая',high),('Критическая',critical)] if v is not None) or 'Не сообщены'
        details=' · '.join(str(sensor.get(key) or '') for key in ('device','component','source') if sensor.get(key))
        content+='<tr><td><b>'+esc(sensor.get('label') or sensor['id'])+'</b><small>'+esc(details)+'</small></td><td><span class="badge '+level+'">'+reading+'</span></td><td>'+esc(limits)+'</td></tr>'
    if any(sensor.get('source')=='ACPI' for sensor in items):content+='<tr><td colspan="3" class="muted">ACPI-зоны не являются заменой датчиков CPU или памяти.</td></tr>'
    return content+'</tbody></table></div><p class="muted">Показаны только датчики, доступные ОС/драйверам. Пределы сообщает источник; автоматические уведомления о температурах не включены.</p></section>'
