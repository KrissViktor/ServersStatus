"""Publish CI packages and a small stable-channel pointer using GitHub CLI."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from agent.github_releases import PLATFORMS,validate_manifest

REPO='KrissViktor/ServersStatus'


def gh(*args,check=True):
    return subprocess.run(['gh',*args,'--repo',REPO],check=check,capture_output=True,text=True)


def ensure(tag,commit):
    if gh('release','view',tag,check=False).returncode==0:return
    result=gh('release','create',tag,'--target',commit,'--title',tag,'--notes','ServersStatus agent build. Installation is controlled from the panel.','--prerelease',check=False)
    if result.returncode:gh('release','view',tag)  # Another platform may create the shared channel concurrently.


def main():
    parser=argparse.ArgumentParser();parser.add_argument('manifest',type=Path);parser.add_argument('file',type=Path)
    args=parser.parse_args()
    if os.environ.get('GITHUB_REPOSITORY')!=REPO or os.environ.get('GITHUB_REF')!='refs/heads/main':
        raise SystemExit('Only the main repository branch may publish')
    data=json.loads(args.manifest.read_text());validate_manifest(data,data['platform'])
    commit=os.environ['GITHUB_SHA']
    if data['version']!=commit[:12]:raise ValueError('Version does not match CI commit')
    kind,filename=PLATFORMS[data['platform']]
    if args.file.name!=filename:raise ValueError('Wrong package filename')
    tag='agent-'+kind+'-'+data['version'];ensure(tag,commit)
    assets=json.loads(gh('release','view',tag,'--json','assets').stdout)['assets']
    names={asset['name'] for asset in assets}
    manifest_name='update-'+kind+'.json'
    with tempfile.TemporaryDirectory() as directory:
        stable=Path(directory)/manifest_name
        if names:
            if filename not in names or manifest_name not in names:raise ValueError('Incomplete existing release; inspect it before retrying')
            gh('release','download',tag,'--pattern',manifest_name,'--dir',directory)
            prior=json.loads(stable.read_text());validate_manifest(prior,data['platform'])
            if prior['version']!=data['version']:raise ValueError('Existing release version mismatch')
        else:
            stable.write_text(json.dumps(data,indent=2),encoding='utf-8')
            gh('release','upload',tag,str(args.file),str(stable))
        ensure('agents-stable',commit)
        # Keep one predecessor so a fresh panel can offer rollback without a long catalog.
        channel_dir=Path(directory)/'channel';channel_dir.mkdir()
        previous_download=gh('release','download','agents-stable','--pattern',manifest_name,'--dir',str(channel_dir),check=False)
        channel=json.loads(stable.read_text())
        if previous_download.returncode==0:
            previous=json.loads((channel_dir/manifest_name).read_text())
            validate_manifest(previous,data['platform'])
            if previous.get('commit_at') and channel.get('commit_at') and previous['commit_at']>channel['commit_at']:return
            if previous['version']!=channel['version']:
                channel['previous']={key:value for key,value in previous.items() if key!='previous'}
            elif previous.get('previous'):
                channel['previous']=previous['previous']
        stable.write_text(json.dumps(channel,indent=2),encoding='utf-8')
        gh('release','upload','agents-stable',str(stable),'--clobber')

if __name__=='__main__':main()
