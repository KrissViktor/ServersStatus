"""Build-time only: acquire a pinned, unmodified official driver installer."""
import hashlib
from pathlib import Path
import urllib.request

SOURCE = 'https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/3d331e3370efb858411f19511373eff65a218701/LibreHardwareMonitor/Resources/PawnIO_setup.exe'
SHA256 = 'a3a46226c5e2824f4cdd42be0eecbabfc672c86f7889710f5ab1e6ad385b47a0'

if __name__ == '__main__':
    with urllib.request.urlopen(SOURCE, timeout=60) as response:
        binary = response.read(10*1024*1024+1)
    if hashlib.sha256(binary).hexdigest() != SHA256:
        raise ValueError('Official PawnIO installer checksum mismatch')
    target = Path('build/hardware-monitor/PawnIO_setup.exe')
    target.write_bytes(binary)
    print('Verified official PawnIO installer bundled')
