import json
import unittest
from pydantic import ValidationError
import test_access_roles as fixture
from server import app as a
from server.temperatures import section

class TemperaturesUiTest(unittest.TestCase):
    setUp=fixture.AccessRolesTest.setUp
    def test_validation_and_snapshot_no_current_substitution(self):
        payload={**self.report,'temperatures':{'status':'available','sampled_at':self.now,'items':[{'id':'cpu','label':'CPU <script>','device':'CPU','source':'hwmon','current':65.5,'critical':100}]}}
        identifier=self.clients['admin'].post('/api/report/pc',headers={'Authorization':'Bearer key'},json=payload).json()['report_id']
        payload['temperatures']['items'][0]['current']=99
        self.clients['admin'].post('/api/report/pc',headers={'Authorization':'Bearer key'},json=payload)
        value=self.clients['admin'].get('/api/history/pc/snapshot',params={'report_id':identifier}).json()['html']
        self.assertIn('65.5 °C',value);self.assertNotIn('99.0 °C',value);self.assertIn('CPU &lt;script&gt;',value);self.assertIn('Температуры',value)
        for current in (float('nan'),float('inf'),300):
            payload['temperatures']['items'][0]['current']=current
            with self.assertRaises(ValidationError):a.Report.model_validate(payload)
    def test_legacy_and_unavailable_do_not_invent_readings(self):
        self.assertEqual('',section({}));self.assertEqual('',section({'temperatures':{'status':'unavailable','items':[]}}))
        self.assertEqual('',section({'temperatures':{'items':[{'id':'cpu','current':None}]}}))
        self.assertNotIn('0.0 °C',section({'temperatures':{'status':'unavailable','items':[]}}))
