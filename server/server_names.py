"""Portal display names are independent of the operating system hostname."""
import json


def display_name(row):
    row = dict(row)
    data = json.loads(row.get('data') or '{}')
    return row.get('display_name') or data.get('hostname') or row['id']


def lookup(connection, agent):
    row = connection.execute("SELECT a.id,p.display_name,r.data FROM agents a LEFT JOIN agent_profiles p ON p.agent=a.id LEFT JOIN current_reports r ON r.agent=a.id WHERE a.id=?", (agent,)).fetchone()
    return display_name(row) if row else agent
