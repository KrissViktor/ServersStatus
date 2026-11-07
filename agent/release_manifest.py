"""Generate CI release metadata for a built package."""
import argparse
import hashlib
import json
from pathlib import Path
from agent.github_releases import BASE,PLATFORMS,validate_manifest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('platform',choices=PLATFORMS);parser.add_argument('version');parser.add_argument('file',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();kind,filename=PLATFORMS[args.platform]
    data={'schema':1,'platform':args.platform,'version':args.version,'sha256':hashlib.sha256(args.file.read_bytes()).hexdigest(),
          'size':args.file.stat().st_size,'download_url':BASE+'agent-'+kind+'-'+args.version+'/'+filename}
    validate_manifest(data,args.platform)
    args.output.write_text(json.dumps(data,indent=2),encoding='utf-8')

if __name__=='__main__':main()
