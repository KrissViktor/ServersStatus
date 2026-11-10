import os
import time
import unittest
from unittest.mock import patch
from agent import reboots
from server.reboots import RebootHistory


class RebootInventoryTest(unittest.TestCase):
    def event(self,code=1074,source='User32',reason='0x80020011'):
        return {'event_id':code,'source':source,'record_id':1,'at':time.time()-10,'reason_code':reason,'message':'x'*1000}

    def test_provider_validated_and_update_requires_reason_code(self):
        info=reboots.sanitize({'events':[self.event(),self.event(reason='0x80000000'),self.event(source='Wrong'),self.event(41,'Microsoft-Windows-Kernel-Power')]})
        RebootHistory.model_validate(info)
        self.assertEqual([e['kind'] for e in info['events']],['update','planned','unexpected'])
        self.assertEqual(len(info['events'][0]['message']),350)

    def test_empty_log_and_malformed_rows(self):
        info=reboots.sanitize({'events':[None,{'event_id':41}]})
        self.assertEqual(info['status'],'available');self.assertEqual(info['events'],[])
        with self.assertRaises(ValueError):reboots.sanitize([])

    def test_background_query_failure_does_not_break_agent(self):
        with patch.object(reboots,'probe',side_effect=RuntimeError('PowerShell returned nonzero')),patch.object(reboots,'_cached',{}),patch.object(reboots,'_busy',True):
            reboots._refresh()
            self.assertEqual(reboots._cached['status'],'unavailable');self.assertFalse(reboots._busy)

    def test_cached_query_runs_once(self):
        with patch.object(reboots.os,'name','nt'),patch.object(reboots,'_next',0),patch.object(reboots,'_busy',False),patch.object(reboots.threading,'Thread') as thread:
            reboots.inventory();reboots.inventory();self.assertEqual(thread.call_count,1)

    @unittest.skipUnless(os.name=='nt','Native Windows System log only')
    def test_native_system_log(self):
        info=reboots.probe();RebootHistory.model_validate(info)
        self.assertEqual(info['status'],'available')
