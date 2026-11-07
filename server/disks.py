"""Space monitoring policy: only the root filesystem for Linux hosts."""


def is_linux(report):
    os_name=str((report.get('system') or {}).get('os','')).casefold()
    disks=report.get('disks',[])
    return os_name=='linux' or (not os_name and bool(disks) and any(d.get('path')=='/' for d in disks) and all(str(d.get('path','')).startswith('/') for d in disks))


def monitored_disks(report):
    disks=report.get('disks',[])
    if is_linux(report):
        return [disk for disk in disks if disk.get('path')=='/'][:1]
    return disks
