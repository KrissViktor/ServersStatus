import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.request import Request
from agent.github_releases import BASE,PLATFORMS,ReleaseRedirect,validate_manifest,validate_url,open_public
from agent.remote_update import download,validate
from server.github_updates import sync
from server import app as application
from fastapi.testclient import TestClient


def release(platform):
    kind,name=PLATFORMS[platform];version='abcdef123456'
    return {'schema':1,'platform':platform,'version':version,'size':7,'sha256':hashlib.sha256(b'package').hexdigest() if platform=='windows-x64' else hashlib.sha256(b'linux!!').hexdigest(),'download_url':BASE+'agent-'+kind+'-'+version+'/'+name}


class ReleaseDownloadTest(unittest.TestCase):
    def test_metadata_and_redirect_allowlist(self):
        data=release('windows-x64');validate_manifest(data,'windows-x64')
        for url in ['http://github.com/x','https://example.com/file',BASE+'../bad','https://github.com.evil.test/file','https://token@github.com/x','https://release-assets.githubusercontent.com/file']:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):validate_manifest({**data,'download_url':url},'windows-x64')
        for url in ['http://release-assets.githubusercontent.com/x','https://evil.test/x','https://github.com/other/repo','https://github.com:444/x']:
            with self.assertRaises(ValueError):validate_url(url,redirect=True)
        validate_url('https://release-assets.githubusercontent.com/asset?signature=secret',redirect=True)
        handler=ReleaseRedirect()
        request=Request(data['download_url'])
        redirected=handler.redirect_request(request,None,302,'Found',{},'https://release-assets.githubusercontent.com/asset?x=1')
        self.assertIsNone(redirected.get_header('Authorization'))
        with self.assertRaises(ValueError):handler.redirect_request(request,None,302,'Found',{},'https://evil.test/file')

    def test_direct_download_never_uses_panel_token(self):
        job={**release('windows-x64'),'id':1};validate(job,'windows-x64')
        with tempfile.TemporaryDirectory() as directory,patch('agent.github_releases.open_public',return_value=io.BytesIO(b'package')) as public,patch('agent.remote_update.request') as panel:
            path=Path(directory)/'package.exe'
            download({'agent_id':'pc','token':'PRIVATE_PANEL_KEY'},job,path)
            self.assertEqual(path.read_bytes(),b'package')
            public.assert_called_once_with(job['download_url']);panel.assert_not_called()
        with patch('agent.github_releases.urllib.request.build_opener') as opener:
            open_public(job['download_url'])
            req=opener.return_value.open.call_args.args[0]
            self.assertNotIn('authorization',{k.lower() for k in req.headers})

    def test_corrupt_direct_download_does_not_replace_existing_file(self):
        job={**release('windows-x64'),'id':1}
        with tempfile.TemporaryDirectory() as directory,patch('agent.github_releases.open_public',return_value=io.BytesIO(b'corrupt')):
            path=Path(directory)/'package.exe';path.write_bytes(b'old')
            with self.assertRaises(ValueError):download({},job,path)
            self.assertEqual(path.read_bytes(),b'old')
            self.assertFalse(path.with_suffix('.partial').exists())


class GitHubCatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr,application,'DB',application.DB);application.DB=str(Path(self.tmp.name)/'db.sqlite3')
        from server.security import limiter
        limiter.reset()
        self.client=TestClient(application.app);self.client.cookies.set('session','session')
        with application.db() as c:
            c.execute('INSERT INTO agents VALUES (?,?)',('pc',application.digest('key')))
            c.execute('INSERT INTO sessions VALUES (?,?)',(application.digest('session'),time.time()+3600))
        self.headers={'Authorization':'Bearer key'}

    def test_sync_idempotence_failure_preserves_catalog_and_legacy_proxy(self):
        with patch('server.github_updates.manifest',side_effect=release):
            self.assertEqual(sync(application.db),2);sync(application.db)
        with application.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM update_packages').fetchone()[0],2)
            package=c.execute("SELECT id FROM update_packages WHERE platform='windows-x64'").fetchone()[0]
        with patch('server.github_updates.manifest',side_effect=[release('windows-x64'),OSError()]):
            with self.assertRaises(OSError):sync(application.db)
        report={'hostname':'pc','cpu_percent':1,'memory_percent':1,'uptime_seconds':1,'disks':[],'agent_version':'old','agent_platform':'windows-x64','features':['remote_update_v1']}
        self.client.post('/api/report/pc',headers=self.headers,json=report)
        import re
        csrf=re.search('name="csrf" value="([^"]+)"',self.client.get('/updates').text).group(1)
        self.assertEqual(self.client.post('/updates/pc',data={'csrf':csrf,'package':package},follow_redirects=False).status_code,303)
        job=self.client.get('/api/agent-update/pc',headers=self.headers).json()['job']
        self.assertEqual(job['download_url'],release('windows-x64')['download_url'])
        with patch('agent.github_releases.open_public',return_value=io.BytesIO(b'package')) as public:
            response=self.client.get('/api/agent-update/pc/'+str(job['id'])+'/package',headers=self.headers)
        self.assertEqual(response.content,b'package');public.assert_called_once_with(job['download_url'])
        self.assertEqual(self.client.get('/api/agent-update/other/'+str(job['id'])+'/package',headers=self.headers).status_code,401)

    def test_check_button_requires_session_and_csrf(self):
        self.assertEqual(self.client.post('/updates/github/check',data={}).status_code,403)
        import re
        csrf=re.search('name="csrf" value="([^"]+)"',self.client.get('/updates').text).group(1)
        with patch('server.github_updates.manifest',side_effect=release):
            self.assertEqual(self.client.post('/updates/github/check',data={'csrf':csrf},follow_redirects=False).status_code,303)
        with patch('server.github_updates.manifest',side_effect=OSError()):
            self.assertEqual(self.client.post('/updates/github/check',data={'csrf':csrf}).status_code,502)
        self.client.cookies.clear()
        self.assertEqual(self.client.post('/updates/github/check',data={'csrf':csrf}).status_code,401)


class ReleasePublicationTest(unittest.TestCase):
    def test_publication_only_from_main_and_immutable_assets(self):
        from agent import publish_release
        from types import SimpleNamespace
        import os
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=release('windows-x64')
            manifest_path=root/'update-windows.json';manifest_path.write_text(json.dumps(data))
            package=root/'ServersStatusService.exe';package.write_bytes(b'package')
            argv=['publish',str(manifest_path),str(package)]
            with patch('sys.argv',argv),patch.dict(os.environ,{'GITHUB_REPOSITORY':'other/repo','GITHUB_REF':'refs/heads/main'}):
                with self.assertRaises(SystemExit):publish_release.main()
            calls=[]
            def gh(*args,**kwargs):
                calls.append(args)
                return SimpleNamespace(returncode=0,stdout=json.dumps({'assets':[]}) if '--json' in args else '')
            with patch('sys.argv',argv),patch.dict(os.environ,{'GITHUB_REPOSITORY':'KrissViktor/ServersStatus','GITHUB_REF':'refs/heads/main','GITHUB_SHA':data['version']+'0'*28}),patch('agent.publish_release.gh',side_effect=gh):
                publish_release.main()
            uploads=[args for args in calls if args[:2]==('release','upload')]
            self.assertEqual(len(uploads),2)
            self.assertNotIn('--clobber',uploads[0])
            self.assertIn('--clobber',uploads[1])
            self.assertEqual(uploads[1][2],'agents-stable')

    def test_ci_rerun_uses_existing_manifest_without_overwriting_package(self):
        from agent import publish_release
        from types import SimpleNamespace
        import os
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=release('windows-x64')
            manifest_path=root/'update-windows.json';manifest_path.write_text(json.dumps(data))
            package=root/'ServersStatusService.exe';package.write_bytes(b'package')
            calls=[]
            def gh(*args,**kwargs):
                calls.append(args)
                if '--json' in args:return SimpleNamespace(returncode=0,stdout=json.dumps({'assets':[{'name':package.name},{'name':manifest_path.name}]}))
                if args[:2]==('release','download'):
                    (Path(args[args.index('--dir')+1])/manifest_path.name).write_text(json.dumps(data))
                return SimpleNamespace(returncode=0,stdout='')
            with patch('sys.argv',['publish',str(manifest_path),str(package)]),patch.dict(os.environ,{'GITHUB_REPOSITORY':'KrissViktor/ServersStatus','GITHUB_REF':'refs/heads/main','GITHUB_SHA':data['version']+'0'*28}),patch('agent.publish_release.gh',side_effect=gh):
                publish_release.main()
            uploads=[args for args in calls if args[:2]==('release','upload')]
            self.assertEqual(len(uploads),1);self.assertEqual(uploads[0][2],'agents-stable')
