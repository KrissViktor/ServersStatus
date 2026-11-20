"""Backup deadlines and verification evidence reported by the agent."""
def timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < 4102444800:
        return value
    return None


def schedule_status(backup, received, now):
    received = timestamp(received)
    stale = received is None or now - received >= 180
    checked_until = min(now, received) if stale and received is not None else now
    created = timestamp(backup.get('created_at'))
    age = backup.get('age_seconds')
    if created is None and backup.get('file') and received and isinstance(age, (int, float)) and age >= 0:
        created = timestamp(received - age)
    deadline = timestamp(backup.get('expected_at'))
    hours = backup.get('max_age_hours', 30)
    if deadline is None and backup.get('schedule', 'daily') == 'daily' and created and isinstance(hours, (int, float)):
        deadline = timestamp(created + hours * 3600)
    overdue = None
    if deadline and checked_until > deadline and backup.get('state') not in ('error', 'future'):
        overdue = checked_until - deadline
    return created, deadline, overdue, stale


def schedule_html(backup, received, now):
    from .dashboard import duration, esc
    from .windows_ui import stamp

    created, deadline, overdue, stale = schedule_status(backup, received, now)
    schedule = 'Ежемесячно' if backup.get('schedule') == 'monthly' else 'Ежедневно'
    fields = [
        ('Расписание', schedule),
        ('Последний файл', stamp(created) if created else 'Дата неизвестна'),
        ('Копия ожидается к', stamp(deadline) if deadline else 'Срок неизвестен'),
    ]
    if overdue:
        fields.append(('Просрочка по последней проверке' if stale else 'Просрочка', duration(overdue)))
    restore = backup.get('restore_check')
    verified = timestamp(restore.get('checked_at')) if isinstance(restore, dict) else None
    result = restore.get('status') if verified and verified <= now else None
    outcomes = {'passed': 'Успешно', 'failed': 'Ошибка проверки'}
    fields.append(('Проверка восстановления', outcomes[result]+' · '+stamp(verified) if isinstance(result, str) and result in outcomes else 'Данных нет'))
    return '<dl class="backup-schedule">'+''.join(
        '<div><dt>'+esc(label)+'</dt><dd>'+esc(value)+'</dd></div>' for label,value in fields
    )+'</dl>'
