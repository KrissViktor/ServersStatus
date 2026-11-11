"""Full report history retention, with bounded and indexed cleanup."""
RETENTION_DAYS=186
CLEANUP_BATCH=10000


def cleanup(connection,now):
    from .portal_settings import retention_days
    days=retention_days(connection)
    row=connection.execute("SELECT next_run FROM report_maintenance WHERE name='retention'").fetchone()
    if row and row['next_run']>now:
        return 0
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='ai_turns'").fetchone():
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='ai_tool_runs'").fetchone():
            connection.execute('DELETE FROM ai_tool_runs WHERE turn IN (SELECT id FROM ai_turns WHERE created<?)',(now-days*86400,))
        connection.execute('DELETE FROM ai_turns WHERE created<?',(now-days*86400,))
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='console_jobs'").fetchone():
        from .console import cleanup_history
        cleanup_history(connection,now)
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='console_grants'").fetchone():
        connection.execute('DELETE FROM console_grants WHERE expires<? OR session NOT IN (SELECT token FROM sessions WHERE expires>?)',(now,now))
        connection.execute('DELETE FROM console_grant_tokens WHERE session NOT IN (SELECT session FROM console_grants)')
        connection.execute('DELETE FROM console_challenges WHERE expires<?',(now,))
        connection.execute('DELETE FROM console_delivery_rate WHERE created<?',(now-60,))
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='process_history'").fetchone():
        connection.execute('DELETE FROM process_history WHERE report IN (SELECT rowid FROM reports WHERE received<? ORDER BY received LIMIT ?)',(now-days*86400,CLEANUP_BATCH))
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='service_history'").fetchone():
        # Keep the last revision before the boundary to describe unchanged services
        # in retained reports; remove earlier obsolete revisions in bounded batches.
        connection.execute('''DELETE FROM service_history WHERE id IN (
            SELECT h.id FROM service_history h WHERE h.received<? AND h.id<>(
                SELECT s.id FROM service_history s WHERE s.agent=h.agent AND s.received<?
                ORDER BY s.received DESC,s.id DESC LIMIT 1) LIMIT ?)''',(now-days*86400,now-days*86400,CLEANUP_BATCH))
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='incident_history'").fetchone():
        connection.execute('DELETE FROM incident_history WHERE closed IS NOT NULL AND closed<?',(now-days*86400,))
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='incident_acknowledgements'").fetchone():
            connection.execute('DELETE FROM incident_acknowledgements WHERE incident NOT IN (SELECT id FROM incident_history)')
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='incident_acknowledgement_comments'").fetchone():
            connection.execute('DELETE FROM incident_acknowledgement_comments WHERE incident NOT IN (SELECT id FROM incident_history)')
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='equipment_history'").fetchone():
        connection.execute('DELETE FROM equipment_history WHERE id IN (SELECT h.id FROM equipment_history h WHERE h.received<? AND h.id<>(SELECT p.id FROM equipment_history p WHERE p.agent=h.agent AND p.received<? ORDER BY p.received DESC,p.id DESC LIMIT 1) LIMIT ?)',(now-days*86400,now-days*86400,CLEANUP_BATCH))
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='server_boot_events'").fetchone():connection.execute('DELETE FROM server_boot_events WHERE at<?',(now-days*86400,))
    connection.execute('DELETE FROM events WHERE received<?',(now-days*86400,))
    cursor=connection.execute('''DELETE FROM reports WHERE rowid IN (
        SELECT rowid FROM reports WHERE received<? ORDER BY received LIMIT ?
    )''',(now-days*86400,CLEANUP_BATCH))
    removed=cursor.rowcount
    delay=60 if removed==CLEANUP_BATCH else 3600
    connection.execute("INSERT INTO report_maintenance VALUES ('retention',?) ON CONFLICT(name) DO UPDATE SET next_run=excluded.next_run",(now+delay,))
    from .portal_backup import note
    note(connection,'retention',detail='Удалено отчётов: '+str(removed),now=now)
    return removed
