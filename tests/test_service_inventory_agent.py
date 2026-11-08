import os
import subprocess
import unittest
from types import SimpleNamespace as NS
import psutil
from agent import service_inventory as inventory


class InventoryCollectionTest(unittest.TestCase):
    def test_windows_details_paused_and_inaccessible_service(self):
        class Service:
            def __init__(self,name,status):self._name=name;self._status=status
            def name(self):return self._name
            def description(self):return 'Detailed service description'
            def as_dict(self):
                if self._status=='denied':raise psutil.AccessDenied()
                return {'name':self._name,'display_name':'Display '+self._name,'status':self._status,'pid':42,'start_type':'automatic','username':'SYSTEM','binpath':'C:/service.exe'}
        data=inventory.windows([Service('sql','running'),Service('paused','paused'),Service('off','stopped'),Service('protected','denied')])
        self.assertEqual(data['total'],4);self.assertEqual(data['unreadable'],1)
        self.assertEqual([s['status'] for s in data['items']],['running','paused','stopped','unavailable'])
        self.assertEqual(data['items'][0]['details']['pid'],'42')
        self.assertEqual(data['items'][0]['details']['description'],'Detailed service description')

    def test_linux_includes_installed_stopped_loaded_and_frozen_services(self):
        calls=[]
        def execute(args,**kwargs):
            calls.append(args)
            if 'list-unit-files' in args:return NS(returncode=0,stdout='sshd.service enabled enabled\nold.service disabled disabled\n')
            if 'list-units' in args:return NS(returncode=0,stdout='transient.service loaded active running Temporary service\n')
            return NS(returncode=0,stdout='Id=sshd.service\nNames=sshd.service\nLoadState=loaded\nActiveState=active\nSubState=running\nDescription=SSH server\nMainPID=123\nUnitFileState=enabled\nExecStart={ path=/usr/sbin/sshd ; argv[]=/usr/sbin/sshd -D ; }\n\nId=old.service\nLoadState=loaded\nActiveState=inactive\nUnitFileState=disabled\n\nId=transient.service\nActiveState=active\nFreezerState=frozen\n')
        data=inventory.linux(execute);entries={s['name']:s for s in data['items']}
        self.assertEqual(set(entries),{'sshd.service','old.service','transient.service'})
        self.assertEqual(entries['sshd.service']['status'],'running')
        self.assertEqual(entries['old.service']['status'],'stopped')
        self.assertEqual(entries['transient.service']['status'],'paused')
        self.assertEqual(entries['sshd.service']['details']['MainPID'],'123')
        self.assertIn('--',calls[-1]);self.assertTrue(all(isinstance(call,list) for call in calls))
        self.assertEqual(inventory.linux(lambda *args,**kwargs:(_ for _ in ()).throw(subprocess.TimeoutExpired('systemctl',8)))['status'],'unavailable')

    def test_background_upload_is_throttled_and_uses_existing_inventory_route(self):
        from unittest.mock import patch
        class Thread:
            def __init__(self,target,daemon):self.target=target
            def start(self):self.target()
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b'{}'
        payload={'status':'available','platform':'linux','items':[]}
        with patch.object(inventory,'_next',0),patch.object(inventory,'_busy',False),patch.object(inventory.time,'monotonic',side_effect=[1,2,62]),patch.object(inventory.threading,'Thread',Thread),patch.object(inventory,'collect',return_value=payload),patch.object(inventory,'request',return_value=Response()) as request:
            for _ in range(3):inventory.handle({'agent_id':'pc','token':'key','server_url':'https://panel.test'})
            self.assertEqual(request.call_count,2)
            self.assertEqual(request.call_args.args[1],'/api/processes/pc/services')

    def test_inventory_is_bounded_without_silent_truncation(self):
        items=[{'name':str(i),'display_name':str(i),'status':'running','details':{}} for i in range(5001)]
        data=inventory.compact(items,'linux');self.assertEqual(len(data['items']),5000);self.assertTrue(data['truncated']);self.assertEqual(data['total'],5001)
        for item in items[:1000]:item['details']={'description':'x'*4096}
        limited=inventory.compact(items[:1000],'windows');self.assertTrue(limited['truncated']);self.assertLess(len(limited['items']),1000)


class LiveServiceInventoryTest(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows SCM only')
    def test_live_read_only_inventory(self):
        data=inventory.windows()
        self.assertEqual(data['status'],'available')
        self.assertGreater(data['total'],0)
        self.assertGreater(len(data['items']),0)
        self.assertTrue(all(isinstance(item['details'],dict) for item in data['items']))

    @unittest.skipUnless(os.name!='nt' and os.path.isdir('/run/systemd/system'),'Live systemd only')
    def test_live_systemd_read_only_inventory(self):
        data=inventory.linux()
        self.assertEqual(data['status'],'available')
        self.assertGreater(data['total'],0)
        self.assertGreater(len(data['items']),0)

