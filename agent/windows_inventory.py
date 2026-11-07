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
    failed = 0
    try:
        server = api.WTS_CURRENT_SERVER_HANDLE
        for session in api.WTSEnumerateSessions(server):
            identifier = session['SessionId']
            try:
                username = api.WTSQuerySessionInformation(server, identifier, api.WTSUserName)
                if not username or api.WTSQuerySessionInformation(server, identifier, api.WTSClientProtocolType) != 2:
                    continue
                domain = api.WTSQuerySessionInformation(server, identifier, api.WTSDomainName)
            except Exception:
                failed += 1
                continue
            result.append({**_rdp_details(api,server,identifier),'session_id': identifier, 'username': username, 'domain': domain,
                           'state': 'active' if session['State'] == 0 else 'disconnected' if session['State'] == 4 else 'other'})
            if len(result) == 200:
                break
    except Exception:
        return {'status': 'unavailable', 'sessions': []}
    return {'status': 'unavailable' if failed and not result else 'available', 'sessions': result, 'partial': bool(failed)}


def _session_times(identifier):
    """WTSINFO timestamps as UTC seconds; missing/zero times remain unknown."""
    if os.name!='nt':return {}
    import ctypes
    class WTSINFO(ctypes.Structure):
        _fields_=[('State',ctypes.c_uint32),('SessionId',ctypes.c_uint32),
            ('IncomingBytes',ctypes.c_uint32),('OutgoingBytes',ctypes.c_uint32),
            ('IncomingFrames',ctypes.c_uint32),('OutgoingFrames',ctypes.c_uint32),
            ('IncomingCompressedBytes',ctypes.c_uint32),('OutgoingCompressedBytes',ctypes.c_uint32),
            ('WinStationName',ctypes.c_wchar*32),('Domain',ctypes.c_wchar*17),('UserName',ctypes.c_wchar*21),
            ('ConnectTime',ctypes.c_int64),('DisconnectTime',ctypes.c_int64),
            ('LastInputTime',ctypes.c_int64),('LogonTime',ctypes.c_int64),('CurrentTime',ctypes.c_int64)]
    library=ctypes.WinDLL('wtsapi32',use_last_error=True)
    query=library.WTSQuerySessionInformationW
    query.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_uint32)]
    query.restype=ctypes.c_int
    free=library.WTSFreeMemory;free.argtypes=[ctypes.c_void_p];free.restype=None
    pointer=ctypes.c_void_p();length=ctypes.c_uint32()
    if not query(None,identifier,24,ctypes.byref(pointer),ctypes.byref(length)):return {}
    try:
        if length.value<ctypes.sizeof(WTSINFO):return {}
        info=WTSINFO.from_buffer_copy(ctypes.string_at(pointer,ctypes.sizeof(WTSINFO)))
        return _time_details(info.LogonTime,info.LastInputTime,info.CurrentTime)
    finally:free(pointer)


def _time_details(logon,last_input,current):
    epoch=11644473600
    result={}
    if logon>epoch*10**7:
        result['logon_at']=logon/10**7-epoch
        if current>=logon:result['duration_seconds']=(current-logon)/10**7
    if last_input>0 and current>=last_input:
        result['idle_seconds']=(current-last_input)/10**7
    return result


def _rdp_details(api,server,identifier):
    import ipaddress
    details={}
    def query(name):
        try:return api.WTSQuerySessionInformation(server,identifier,getattr(api,name))
        except Exception:return None
    name=query('WTSClientName')
    if isinstance(name,str):details['client_name']=name[:255]
    address=query('WTSClientAddress')
    if isinstance(address,dict):
        raw=address.get('Address')
        try:
            if isinstance(raw,str):
                ip=ipaddress.ip_address(raw)
                if not ip.is_unspecified:details['client_address']=str(ip)
            # WTS_CLIENT_ADDRESS IPv4 starts at offset 2, as defined by WTS.
            if address.get('AddressFamily')==2 and isinstance(raw,(bytes,tuple,list)) and len(raw)>=6:
                ip=ipaddress.IPv4Address(bytes(raw[2:6]))
                if not ip.is_unspecified:details['client_address']=str(ip)
        except (ValueError,TypeError):pass
    try:details.update(_session_times(identifier))
    except Exception:pass
    return details
