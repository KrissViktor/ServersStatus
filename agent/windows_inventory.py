"""Read-only Windows service discovery and Terminal Services sessions."""
import os
import psutil


def discover_services():
    if os.name != 'nt':
        return []
    found = []
    try:
        for service in psutil.win_service_iter():
            try:
                info = service.as_dict()
                name = info.get('name', '')
                display = info.get('display_name', '')
                text = (name + ' ' + display).casefold()
                sql = name.casefold() == 'mssqlserver' or name.casefold().startswith('mssql$') or name.casefold()=='sqlserveragent' or name.casefold().startswith('sqlagent$')
                one_c = any(word in text for word in ('1c:enterprise', '1с:предприятие', '1c enterprise', '1c:предприятие'))
                if sql or one_c:
                    found.append({'name': name, 'display_name': display, 'status': info['status'], 'kind': 'SQL' if sql else '1C'})
            except (OSError, psutil.Error):
                continue
    except (OSError, psutil.Error):
        return []
    return found[:100]


def rdp_sessions(api=None):
    if api is None:
        if os.name != 'nt':
            return {'status': 'unsupported', 'sessions': []}
        try:
            import win32ts as api
        except ImportError:
            return {'status': 'unavailable', 'sessions': []}
    result = []
    try:
        server = api.WTS_CURRENT_SERVER_HANDLE
        for session in api.WTSEnumerateSessions(server):
            identifier = session['SessionId']
            username = api.WTSQuerySessionInformation(server, identifier, api.WTSUserName)
            if not username:
                continue
            if api.WTSQuerySessionInformation(server, identifier, api.WTSClientProtocolType) != 2:
                continue
            domain = api.WTSQuerySessionInformation(server, identifier, api.WTSDomainName)
            result.append({'session_id': identifier, 'username': username, 'domain': domain,
                           'state': 'active' if session['State'] == 0 else 'disconnected' if session['State'] == 4 else 'other'})
            if len(result) == 200:
                break
    except Exception:
        return {'status': 'unavailable', 'sessions': []}
    return {'status': 'available', 'sessions': result}
