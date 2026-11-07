import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
import psutil
from agent.processes import begin,finish
from agent.windows_inventory import _time_details,_rdp_details


class ProcessCollectionTest(unittest.TestCase):
    def test_normalized_cpu_pid_reuse_and_denied_fields(self):
        before=[NS(info={'pid':1,'create_time':5,'cpu_times':NS(user=1,system=1)}),NS(info={'pid':2,'create_time':5,'cpu_times':NS(user=1,system=1)})]
        after=[NS(info={'pid':1,'create_time':5,'cpu_times':NS(user=3,system=1),'name':'sql','username':'user','memory_info':NS(rss=2048),'status':'running'}),NS(info={'pid':2,'create_time':6,'cpu_times':None,'name':'hidden','username':None,'memory_info':None,'status':None})]
        with patch('agent.processes.psutil.process_iter',side_effect=[before,after]),patch('agent.processes.psutil.cpu_count',return_value=4),patch('agent.processes.time.perf_counter',side_effect=[10,10,11]):
            result=finish(begin())
        self.assertEqual(result['items'][0]['cpu_percent'],50)
        self.assertEqual(result['items'][0]['memory_bytes'],2048)
        self.assertIsNone(result['items'][1]['cpu_percent'])
        self.assertIsNone(result['items'][1]['memory_bytes'])
        self.assertEqual(result['unreadable'],1)
        self.assertEqual(result['total'],2)

    def test_process_limit_and_unavailable(self):
        process=NS(info={'pid':1,'create_time':5,'name':'x','username':'u','memory_info':None,'status':'running'})
        with patch('agent.processes.MAX_PROCESSES',1),patch('agent.processes.psutil.process_iter',return_value=[process,process]):
            result=finish({})
        self.assertTrue(result['truncated']);self.assertEqual(result['total'],2);self.assertEqual(len(result['items']),1)
        with patch('agent.processes.psutil.process_iter',side_effect=psutil.AccessDenied()):
            self.assertEqual(finish({})['status'],'unavailable')

    def test_rdp_native_times_and_optional_client_fields(self):
        logon=(1700000000+11644473600)*10**7
        result=_time_details(logon,logon+60*10**7,logon+120*10**7)
        self.assertEqual(result,{'logon_at':1700000000,'duration_seconds':120,'idle_seconds':60})
        self.assertEqual(_time_details(0,0,0),{})
        class API:
            WTSClientName=1;WTSClientAddress=2
            @staticmethod
            def WTSQuerySessionInformation(server,identifier,field):
                return 'TSD-PC' if field==1 else {'AddressFamily':2,'Address':bytes([0,0,192,168,1,2]+[0]*14)}
        with patch('agent.windows_inventory._session_times',return_value=result):
            details=_rdp_details(API,0,1)
        self.assertEqual(details['client_address'],'192.168.1.2')
        self.assertEqual(details['client_name'],'TSD-PC')
        self.assertEqual(details['duration_seconds'],120)
        API.WTSQuerySessionInformation=lambda *args: (_ for _ in ()).throw(OSError())
        with patch('agent.windows_inventory._session_times',side_effect=OSError()):self.assertEqual(_rdp_details(API,0,1),{})


