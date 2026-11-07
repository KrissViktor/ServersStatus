from pathlib import Path
import platform
import re

def version():
    try:
        value=Path(__file__).with_name('VERSION').read_text().strip()
        return value if re.fullmatch(r'[A-Za-z0-9._-]{1,80}',value) else 'dev'
    except OSError:
        return 'dev'

def agent_platform():
    return 'windows-x64' if platform.system()=='Windows' else 'linux-source' if platform.system()=='Linux' else 'unsupported'
