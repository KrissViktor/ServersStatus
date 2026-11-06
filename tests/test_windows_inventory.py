import unittest
from types import SimpleNamespace
from unittest.mock import patch
from agent.windows_inventory import rdp_sessions,discover_services

class WindowsInventoryTest(unittest.TestCase):
    def test_rdp_only_users_active_and_disconnected(self):
        class API:
            WTS_CURRENT_SERVER_HANDLE=0
            WTSUserName=1
            WTSDomainName=2
            WTSClientProtocolType=3
            @staticmethod
            def WTSEnumerateSessions(server):
                return [{'SessionId':1,'State':0},{'SessionId':2,'State':4},{'SessionId':3,'State':0}]
            @staticmethod
            def WTSQuerySessionInformation(server,identifier,field):
                if field==1:return 'user'+str(identifier)
                if field==2:return 'DOMAIN'
                return 0 if identifier==3 else 2
        result=rdp_sessions(API)
        self.assertEqual(result['status'],'available')
        self.assertEqual([s['username'] for s in result['sessions']],['user1','user2'])
        self.assertEqual(result['sessions'][1]['state'],'disconnected')
        API.WTSEnumerateSessions=lambda server: (_ for _ in ()).throw(OSError())
        self.assertEqual(rdp_sessions(API)['status'],'unavailable')

    def test_service_discovery_filters_1c_sql(self):
        services=[{'name':'MSSQLSERVER','display_name':'SQL Server','status':'running'},
                  {'name':'ragent','display_name':'1C:Enterprise 8.3 Server Agent','status':'stopped'},
                  {'name':'Spooler','display_name':'Print spooler','status':'running'}]
        with patch('agent.windows_inventory.os.name','nt'),patch('agent.windows_inventory.psutil.win_service_iter',create=True,return_value=[SimpleNamespace(as_dict=lambda s=s:s) for s in services]):
            found=discover_services()
        self.assertEqual([s['kind'] for s in found],['SQL','1C'])
