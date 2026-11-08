"""Full report history retention, with bounded and indexed cleanup."""
RETENTION_DAYS=186
CLEANUP_BATCH=10000


def cleanup(connection,now):
    row=connection.execute("SELECT next_run FROM report_maintenance WHERE name='retention'").fetchone()
    if row and row['next_run']>now:
        return 0
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='console_jobs'").fetchone():
        from .console import cleanup_history
        cleanup_history(connection,now)
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='console_grants'").fetchone():
        connection.execute('DELETE FROM console_grants WHERE expires<? OR session NOT IN (SELECT token FROM sessions WHERE expires>?)',(now,now))
        connection.execute('DELETE FROM console_grant_tokens WHERE session NOT IN (SELECT session FROM console_grants)')
        connection.execute('DELETE FROM console_challenges WHERE expires<?',(now,))
        connection.execute('DELETE FROM console_delivery_rate WHERE created<?',(now-60,))
    cursor=connection.execute('''DELETE FROM reports WHERE rowid IN (
        SELECT rowid FROM reports WHERE received<? ORDER BY received LIMIT ?
    )''',(now-RETENTION_DAYS*86400,CLEANUP_BATCH))
    removed=cursor.rowcount
    delay=60 if removed==CLEANUP_BATCH else 3600
    connection.execute("INSERT INTO report_maintenance VALUES ('retention',?) ON CONFLICT(name) DO UPDATE SET next_run=excluded.next_run",(now+delay,))
    return removed
