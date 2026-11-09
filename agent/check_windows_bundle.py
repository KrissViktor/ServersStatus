"""Build gate: reject hardware helpers/driver installers in the frozen agent."""
import sys


def validate_entries(entries):
    names=[name.replace('\\','/').lower() for name in entries]
    forbidden=('pawnio','librehardwaremonitor','openhardwaremonitor','hardware-monitor','install_sensor_driver')
    if any(any(token in name for token in forbidden) for name in names):
        raise ValueError('Forbidden hardware driver/helper in Windows bundle')
    if 'agent/temperature_sensors.ps1' not in names:
        raise ValueError('Missing native Windows temperature probe')


if __name__=='__main__':
    from PyInstaller.archive.readers import CArchiveReader
    validate_entries(CArchiveReader(sys.argv[1]).toc)
    print('Windows bundle verified: no hardware driver/helper payloads')
