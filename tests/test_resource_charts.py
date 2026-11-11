"""Resource history keeps peaks, gaps, access rules and exact report ordering."""
import json
import time
import unittest
import test_access_roles as fixtures
from server import app as a
from server.resource_charts import metadata


class ResourceChartsTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AccessRolesTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.clients['admin'];self.now=time.time();self.start=self.now-600
        with a.db() as c:
            c.execute('INSERT INTO agents VALUES (?,?)',('other',a.digest('other-test')))
            c.execute('DELETE FROM reports WHERE agent=?',('pc',))
            self.ids=[]
            for offset,cpu in [(0,10),(10,99),(20,20),(350,40),(360,50)]:
                data={'cpu_percent':cpu,'memory_percent':25,'system':{'memory_total_bytes':16*1024**3,'memory_available_bytes':12*1024**3}}
                self.ids.append(c.execute('INSERT INTO reports VALUES (?,?,?)',('pc',self.start+offset,json.dumps(data))).lastrowid)
            self.foreign=c.execute('INSERT INTO reports VALUES (?,?,?)',('other',self.start+10,json.dumps({'cpu_percent':999}))).lastrowid
            self.duplicate=c.execute('INSERT INTO reports VALUES (?,?,?)',('pc',self.start+10,json.dumps({'cpu_percent':80,'memory_percent':30}))).lastrowid
            c.execute('INSERT INTO incident_history(key,agent,category,opened,last_seen,message) VALUES (?,?,?,?,?,?)',('example:pc','pc','service',self.start+50,self.start+50,'Проверить SQL'))
            c.execute('INSERT INTO server_boot_events VALUES (?,?,?,?,?,?,?,?)',('pc','System',1,self.start+100,6005,'boot','Запуск',''))

    def resources(self,**kwargs):
        return self.client.get('/api/history/pc/resources',params={'start':self.start-1,'end':self.now,**kwargs})

    def test_aggregates_keep_real_peaks_minima_counts_and_gaps(self):
        data=self.resources().json();points=data['points']
        self.assertLessEqual(len(points),361)
        self.assertEqual(sum(p['samples'] for p in points),6)
        self.assertEqual(max(p['cpu_peak'] for p in points),99)
        self.assertEqual(min(p['cpu_min'] for p in points),10)
        self.assertTrue(any(p['has_gap'] for p in points))
        self.assertTrue(all(p['cpu']>0 for p in points))
        self.assertEqual({p['kind'] for p in data['events']},{'incident','boot'})
        self.assertEqual(points[0]['ram_used_bytes'],4*1024**3)
        self.assertNotIn('data',points[0]);self.assertEqual(self.resources().headers['cache-control'],'no-store')

    def test_invalid_ranges_roles_and_agent_isolation(self):
        for params in [{'period':'bad'},{'start':self.now,'end':self.start},{'start':'nan','end':self.now},{'start':0,'end':2678401}]:
            self.assertEqual(self.resources(**params).status_code,400,params)
        self.assertEqual(self.client.get('/api/history/pc/resources',params={'start':self.start}).status_code,400)
        self.assertEqual(self.client.get('/api/history/missing/resources').status_code,404)
        for path in ['/api/history/pc/resources','/api/history/pc/report-step?report_id=1&direction=1']:
            self.assertEqual(self.fixture.clients['reader'].get(path).status_code,403)
        self.client.cookies.clear();self.assertEqual(self.resources().status_code,401)

    def step(self,identifier,direction):
        return self.client.get('/api/history/pc/report-step',params={'report_id':identifier,'direction':direction})

    def test_adjacent_reports_use_timestamp_and_id_even_for_duplicate_times(self):
        self.assertEqual(self.step(self.ids[1],1).json()['report_id'],self.duplicate)
        self.assertEqual(self.step(self.duplicate,-1).json()['report_id'],self.ids[1])
        self.assertEqual(self.step(self.duplicate,1).json()['report_id'],self.ids[2])
        self.assertIsNone(self.step(self.ids[0],-1).json()['report_id'])
        self.assertIsNone(self.step(self.ids[-1],1).json()['report_id'])
        self.assertEqual(self.step(self.foreign,1).status_code,404)
        self.assertEqual(self.step(self.ids[0],0).status_code,400)
        self.assertEqual(self.step(2**70,1).status_code,400)

    def test_raw_cpu_report_includes_ram_without_full_inventory(self):
        response=self.client.get('/api/history/pc/detail',params={'center':self.start,'count':3,'metric':'cpu'})
        point=response.json()['points'][0]
        self.assertEqual(point['cpu'],10);self.assertEqual(point['ram'],25)
        self.assertEqual(point['ram_used_bytes'],4*1024**3)
        self.assertNotIn('system',point)

    def test_metadata_omits_secrets_and_unusable_numbers(self):
        value=metadata([{'timestamp':10,'cpu':float('nan'),'ram':30,'console':'PRIVATE','data':'PRIVATE','ram_total_bytes':16}],'cpu',0,20)
        self.assertNotIn('PRIVATE',value);self.assertNotIn('NaN',value)
        self.assertIn('data-resource-metric="cpu"',value)

    def test_selected_duplicate_report_is_retained_in_small_window(self):
        with a.db() as c:
            for _ in range(40):
                identifier=c.execute('INSERT INTO reports VALUES (?,?,?)',('pc',self.start+10,json.dumps({'cpu_percent':15,'memory_percent':30}))).lastrowid
        response=self.client.get('/api/history/pc/detail',params={'center':self.start+10,'count':3,'report_id':identifier})
        self.assertEqual(response.status_code,200)
        self.assertIn(identifier,[p['report_id'] for p in response.json()['points']])
        self.assertEqual(self.client.get('/api/history/pc/detail',params={'center':self.start,'report_id':self.foreign}).status_code,404)

    def test_short_history_period_has_matching_page_context(self):
        response=self.client.get('/history/pc?period=15m')
        self.assertEqual(response.status_code,200)
        self.assertIn('data-resource-period="15m"',response.text)
        self.assertIn('средние за 10 с.',response.text)
