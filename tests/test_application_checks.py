import os
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch,MagicMock
from agent import application_checks as checks
from agent.service_names import executable_name,process_fields


class CheckTest(unittest.TestCase):
    def rule(self,**kwargs):
        return checks.validate_rules([{'id':'health','name':'App','kind':'http','target':'http://127.0.0.1/','contains':'ready',**kwargs}])[0]

    def test_live_http_content_redirect_and_tcp(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path=='/redirect':self.send_response(302);self.send_header('Location','/');self.end_headers();return
                self.send_response(200);self.end_headers();self.wfile.write(b'ready')
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)
            self.assertEqual(checks.check(self.rule(target=url))['status'],'ok')
            self.assertEqual(checks.check(self.rule(target=url,contains='missing'))['status'],'failed')
            self.assertEqual(checks.check(self.rule(target=url+'/redirect'))['status'],'failed')
            self.assertEqual(checks.check(self.rule(kind='tcp',target='127.0.0.1',port=server.server_port))['status'],'ok')
        finally:server.shutdown();server.server_close();thread.join()

    def test_invalid_rules_and_opt_in(self):
        for target in ['file:///etc/passwd','https://u:p@example.com/','https://example.com/?token=secret','http://example.com/#fragment']:
            with self.assertRaises(ValueError):self.rule(target=target)
        self.assertFalse(checks.inventory({'application_checks':[self.rule()]})['enabled'])
        with self.assertRaises(ValueError):checks.validate_rules([self.rule()]*7)

    def test_checks_cache_and_fixed_sql_query(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'checks.json';value={'revision':123,'checks':[self.rule()]}
            self.assertEqual(checks.save_cache(path,value),checks.load_cache(path))
        rule=self.rule(kind='sql',target='localhost',port=1433,database='master')
        with patch.object(checks.os,'name','nt'),patch.object(checks,'Path',return_value=MagicMock()) ,patch.object(checks.subprocess,'run') as run:
            self.assertEqual(checks.check(rule)['status'],'ok')
            self.assertIn("CommandText='SELECT 1'",run.call_args.args[0][-1]);self.assertIn('IntegratedSecurity=$true',run.call_args.args[0][-1])
            self.assertEqual(run.call_args.kwargs['timeout'],8)

    def test_linux_service_executable_from_main_pid_and_config(self):
        from types import SimpleNamespace
        from agent.linux_inventory import systemd_services
        execute=lambda *args,**kwargs:SimpleNamespace(stdout='Id=app.service\nLoadState=loaded\nActiveState=active\nMainPID=123\nExecStart={ path=/usr/bin/app ; argv[]=/usr/bin/app --secret hidden ; }')
        with patch('psutil.Process') as process:
            process.return_value.name.return_value='app'
            self.assertEqual(systemd_services(['app'],execute)[0]['executable'],'app')
        execute=lambda *args,**kwargs:SimpleNamespace(stdout='Id=app.service\nLoadState=loaded\nActiveState=inactive\nMainPID=0\nExecStart={ path=/usr/bin/app ; argv[]=/usr/bin/app --secret hidden ; }')
        self.assertEqual(systemd_services(['app'],execute)[0]['executable_source'],'configuration')

    def test_service_executable_arguments_are_not_exposed(self):
        self.assertEqual(executable_name('"C:\\Program Files\\Microsoft SQL Server\\sqlservr.exe" -s INSTANCE'),'sqlservr.exe')
        self.assertEqual(executable_name('C:\\Program Files\\App\\worker.EXE --password secret'),'worker.EXE')
        with patch('agent.service_names.psutil.Process') as process:
            process.return_value.name.return_value='sqlservr.exe'
            self.assertEqual(process_fields({'pid':10,'binpath':'wrong.exe'})['executable_source'],'process')
        self.assertEqual(process_fields({'pid':0,'binpath':'C:\\App\\service.exe --key secret'}),{'executable':'service.exe','executable_source':'configuration'})
