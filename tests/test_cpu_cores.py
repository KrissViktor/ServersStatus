import json
import re
import time
import unittest
from pydantic import ValidationError
import test_access_roles as fixture
from server import app as a
from server.cpu_cores import render

class CpuCoresTest(unittest.TestCase):
    setUp=fixture.AccessRolesTest.setUp
    def insert(self,values,offset=0,agent='pc'):
        data={**self.report,'cpu_per_core':values,'system':{'physical_cores':2,'logical_cores':len(values)}}
        with a.db() as c:return c.execute('INSERT INTO reports VALUES (?,?,?)',(agent,self.now+offset,json.dumps(data))).lastrowid
    def test_validation_and_old_agent_compatibility(self):
        self.assertEqual(a.Report.model_validate(self.report).cpu_per_core,[])
        self.assertEqual(a.Report.model_validate({**self.report,'cpu_per_core':[0,100,None]}).cpu_per_core,[0,100,None])
        for value in ([101],[-1],[float('nan')],[0]*1025):
            with self.subTest(value=str(value)[:20]),self.assertRaises(ValidationError):a.Report.model_validate({**self.report,'cpu_per_core':value})
    def test_current_and_snapshot_per_core_history_and_exact_values(self):
        before=self.insert([10,20],-10);center=self.insert([80,30]);after=self.insert([40,60],10)
        response=self.clients['admin'].get('/api/servers/pc/cpu-cores',params={'report_id':center})
        self.assertEqual(response.status_code,200);self.assertEqual(response.headers['cache-control'],'no-store');value=response.json()
        self.assertEqual(value['count'],2);self.assertIn('80.0%',value['html']);self.assertIn('CPU 0',value['html']);self.assertIn('CPU 1',value['html'])
        self.assertEqual(value['html'].count('class="task-snapshot-marker"'),2)
        self.assertIn('data-detail-metric="cpu_core"',value['html']);self.assertIn('data-detail-name="1"',value['html'])
        detail=self.clients['admin'].get('/api/history/pc/detail',params={'metric':'cpu_core','name':'1','center':self.now,'count':10}).json()
        lookup={p['report_id']:p['value'] for p in detail['points']}
        self.assertEqual([lookup[identifier] for identifier in (before,center,after)],[20,30,60]);self.assertEqual(detail['unit'],'%')
        self.assertEqual(self.clients['reader'].get('/api/servers/pc/cpu-cores').status_code,403)
        self.assertEqual(self.clients['admin'].get('/api/history/pc/detail',params={'metric':'cpu_core','name':'-1','center':self.now}).status_code,400)
        self.assertEqual(self.clients['admin'].get('/api/servers/other/cpu-cores',params={'report_id':center}).status_code,404)
    def test_legacy_snapshot_is_not_filled_from_current_and_pagination(self):
        old=self.insert([],-100)
        latest=self.insert([20]*40)
        old_data=self.clients['admin'].get('/api/servers/pc/cpu-cores',params={'report_id':old}).json()
        self.assertEqual(old_data['count'],0);self.assertIn('не сохранялась',old_data['html'])
        with a.db() as c:
            first=render(c,'pc',latest);second=render(c,'pc',latest,32)
        self.assertEqual(first['html'].count('class="cpu-core"'),32);self.assertEqual(second['html'].count('class="cpu-core"'),8)
        self.assertIn('CPU 39',second['html']);self.assertNotIn('>CPU 0</button>',second['html'])
        with a.db() as c:clamped=render(c,'pc',latest,100)
        self.assertEqual(clamped['offset'],32);self.assertEqual(clamped['html'].count('class="cpu-core"'),8)
    def test_snapshot_contains_lazy_controls_with_exact_report(self):
        identifier=self.insert([10,80])
        value=self.clients['admin'].get('/api/history/pc/snapshot',params={'report_id':identifier}).json()['html']
        self.assertIn('data-cpu-cores',value);self.assertIn('cpu-cores?report_id='+str(identifier),value);self.assertNotIn('class="cpu-core"',value)
