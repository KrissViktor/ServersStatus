"""Translate release metadata without changing Git refs or release assets."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
from agent.publish_release import REPO,RELEASE_NOTES,release_title

ENGLISH_NOTES='ServersStatus agent build. Installation is controlled from the panel.'


def translation(release):
    tag=release['tag_name'];body=(release.get('body') or '').strip()
    changes={}
    if body==ENGLISH_NOTES:changes['body']=RELEASE_NOTES
    elif body and body!=RELEASE_NOTES and not re.search('[А-Яа-яЁё]',body):
        raise ValueError('Найдено нестандартное описание, требуется отдельный перевод: '+tag)
    title=release.get('name') or tag
    translated=release_title(tag)
    if title==tag and translated!=tag:changes['name']=translated
    return changes


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    result=subprocess.run(['gh','api',f'repos/{REPO}/releases','--paginate','--slurp'],check=True,capture_output=True,text=True)
    releases=[release for page in json.loads(result.stdout) for release in page]
    # Validate the entire catalog before making the first change.
    planned=[(release,translation(release)) for release in releases]
    changed=0
    with tempfile.TemporaryDirectory() as directory:
        payload=Path(directory)/'release.json'
        for release,changes in planned:
            if not changes:continue
            print(('Перевод: ' if args.apply else 'Будет переведено: ')+release['tag_name'])
            if args.apply:
                payload.write_text(json.dumps(changes,ensure_ascii=False),encoding='utf-8')
                subprocess.run(['gh','api','--method','PATCH',f'repos/{REPO}/releases/{release["id"]}','--input',str(payload)],check=True,capture_output=True,text=True)
            changed+=1
    print(f'Всего релизов: {len(releases)}. '+('Обновлено: ' if args.apply else 'Запланировано: ')+str(changed))


if __name__=='__main__':main()
