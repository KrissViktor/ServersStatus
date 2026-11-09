"""Preserve NuGet licensing metadata and package-supplied license texts."""
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parent
assets = json.loads((root/'obj/project.assets.json').read_text(encoding='utf-8-sig'))
destination = root.parents[1]/'build/hardware-monitor'
licenses = destination/'licenses'
licenses.mkdir(parents=True, exist_ok=True)
notices = []
for name, library in sorted(assets['libraries'].items()):
    if library['type'] != 'package':
        continue
    package = next(Path(folder)/library['path'] for folder in assets['packageFolders']
                   if (Path(folder)/library['path']).is_dir())
    files = list(package.glob('*.nuspec'))
    if not files:
        raise ValueError('Missing package licensing metadata: '+name)
    metadata = ET.parse(files[0]).getroot()
    def field(tag):
        return next((node.text or '' for node in metadata.iter() if node.tag.split('}')[-1] == tag), '')
    notices.append(name+'\nAuthors: '+field('authors')+'\nCopyright: '+field('copyright')+
                   '\nLicense: '+field('license')+'\nLicense URL: '+field('licenseUrl')+
                   '\nProject: '+field('projectUrl')+'\n')
    target = licenses/name.replace('/', '-')
    target.mkdir(exist_ok=True)
    shutil.copy2(files[0], target/files[0].name)
    for file in package.rglob('*'):
        if file.is_file() and ('license' in file.name.lower() or 'notice' in file.name.lower()) and file.suffix.lower() in ('.txt','.md',''):
            shutil.copy2(file, target/file.name)
(destination/'NuGet-NOTICES.txt').write_text('\n'.join(notices), encoding='utf-8')
# Runtime packs are restore downloads rather than ordinary libraries.
for framework in assets['project']['frameworks'].values():
    for dependency in framework.get('downloadDependencies', []):
        if dependency['name'].lower() != 'microsoft.netcore.app.runtime.win-x64':
            continue
        version = dependency['version'].strip('[]').split(',')[0].strip()
        package = next(Path(folder)/dependency['name'].lower()/version
                       for folder in assets['packageFolders']
                       if (Path(folder)/dependency['name'].lower()/version).is_dir())
        target = licenses/('Microsoft.NETCore.App.Runtime.win-x64-'+version)
        target.mkdir(exist_ok=True)
        for name in ('LICENSE.TXT','THIRD-PARTY-NOTICES.TXT'):
            shutil.copy2(package/name, target/name)
