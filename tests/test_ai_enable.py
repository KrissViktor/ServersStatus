import http.server
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest


@unittest.skipUnless(os.name!='nt' and shutil.which('bash') and shutil.which('curl'),'Bash and curl required')
class EnableAITest(unittest.TestCase):
    def test_hidden_key_validation_and_atomic_preservation_on_bad_key(self):
        expected='testBase64Key1234567890=='
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                good=self.path=='/health' or (self.path=='/v1/models' and self.headers.get('Authorization')=='Bearer '+expected)
                self.send_response(200 if good else 401);self.end_headers();self.wfile.write(b'{"status":"ok"}')
            def log_message(self,*args):pass
        server=http.server.HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);bin_dir=root/'bin';bin_dir.mkdir();state=root/'state';state.mkdir()
            for name in ['id','chown','systemctl']:
                stub=bin_dir/name;stub.write_text('#!/bin/sh\nexit 0\n');stub.chmod(0o755)
            source=Path('deploy/ai-ssh/Enable-PortalAI.sh').read_text().replace('[[ ${EUID} -eq 0 ]]','true').replace('/var/lib/serversstatus',str(state)).replace('127.0.0.1:18091','127.0.0.1:'+str(server.server_port))
            script=root/'enable.sh';script.write_text(source)
            env={**os.environ,'PATH':str(bin_dir)+os.pathsep+os.environ['PATH'],'HTTP_PROXY':'http://127.0.0.1:1','http_proxy':'http://127.0.0.1:1','NO_PROXY':'','no_proxy':''}
            result=subprocess.run(['bash',str(script)],input=expected+'\n',capture_output=True,text=True,env=env,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            file=state/'ai-api-key';self.assertEqual(file.read_text(),expected);self.assertEqual(file.stat().st_mode&0o777,0o600)
            self.assertNotIn(expected,result.stdout+result.stderr)
            bad=subprocess.run(['bash',str(script)],input='incorrectKey1234567890\n',capture_output=True,text=True,env=env,timeout=10)
            self.assertNotEqual(bad.returncode,0);self.assertEqual(file.read_text(),expected)
