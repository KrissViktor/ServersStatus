import json
from pathlib import Path
import tempfile
import time
import unittest
import zlib
from fastapi.testclient import TestClient
from server import app as a
from server.snapshots import extrema
from server.retention import cleanup,RETENTION_DAYS


class HistoricalSnapshotsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr,a,'DB',a.DB);a.DB=str(Path(self.tmp.name)/'db.sqlite3')
        from server.security import limiter
        limiter.reset()
        self.now=time.time();self.client=TestClient(a.app,base_url='https://testserver');self.client.cookies.set('session','test')
        self.headers={'Authorization':'Bearer key'}
        with a.db() as c:
            c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest('test'),self.now+3600))
            c.execute('INSERT INTO agents VALUES (?,?)',('pc',a.digest('key')))
            c.execute('INSERT INTO agents VALUES (?,?)',('other',a.digest('other-key')))
        self.data={'hostname':'PC','cpu_percent':75,'memory_percent':40,'uptime_seconds':1000,'system':{'os':'Windows','memory_total_bytes':20*1024**3,'memory_used_bytes':8*1024**3},'disks':[],'features':['console_v1'],'console':{'enabled':True,'shell':'powershell','identity':'SECRET-IDENTITY'}}

    def report(self):
        response=self.client.post('/api/report/pc',headers=self.headers,json=self.data)
        self.assertEqual(response.status_code,200);return response.json()

    def processes(self,report,name='<SQL>',count=1):
        return self.client.post('/api/processes/pc',headers=self.headers,json={'status':'available','report_id':report['report_id'],'report_received':report['report_received'],'total':count,'items':[{'pid':i+1,'name':name+str(i),'username':'user','cpu_percent':i%100,'memory_bytes':(i+1)*1024**2} for i in range(count)]})

    def test_snapshot_keeps_original_values_and_processes_without_live_controls(self):
        first=self.report();self.assertEqual(self.processes(first).status_code,200)
        self.data.update(cpu_percent=1,memory_percent=5);second=self.report();self.processes(second,'CURRENT')
        response=self.client.get('/api/history/pc/snapshot',params={'report_id':first['report_id']})
        self.assertEqual(response.status_code,200);self.assertEqual(response.headers['cache-control'],'no-store')
        value=response.json();self.assertTrue(value['processes_available']);html=value['html']
        self.assertIn('75.0',html);self.assertIn('&lt;SQL&gt;0',html);self.assertNotIn('CURRENT',html)
        self.assertIn('Снимок',html);self.assertNotIn('0 с назад',html)
        for hidden in ('SECRET-IDENTITY','console_v1','data-rdp-action','remote-console'):
            self.assertNotIn(hidden,html)
        self.assertEqual(self.client.get('/api/history/other/snapshot',params={'report_id':first['report_id']}).status_code,404)
        self.client.cookies.clear();self.assertEqual(self.client.get('/api/history/pc/snapshot',params={'report_id':first['report_id']}).status_code,401)

    def test_compact_history_is_capped_linked_and_not_filled_from_current(self):
        first=self.report();self.assertEqual(self.processes(first,count=1000).status_code,200)
        with a.db() as c:
            blob=c.execute('SELECT data FROM process_history WHERE report=?',(first['report_id'],)).fetchone()[0]
            archived=json.loads(zlib.decompress(blob));self.assertLessEqual(len(archived['items']),20)
            self.assertEqual(len(archived['cpu_pids']),10);self.assertEqual(len(archived['ram_pids']),10)
        bad={**first,'report_received':first['report_received']+1}
        self.assertEqual(self.processes(bad).status_code,409)
        other=self.client.post('/api/report/other',headers={'Authorization':'Bearer other-key'},json=self.data).json()
        self.assertEqual(self.processes(other).status_code,409)
        legacy=self.report()
        self.client.post('/api/processes/pc',headers=self.headers,json={'status':'available','items':[{'pid':1,'name':'LATEST_ONLY'}]})
        snapshot=self.client.get('/api/history/pc/snapshot',params={'report_id':legacy['report_id']}).json()
        self.assertFalse(snapshot['processes_available']);self.assertNotIn('LATEST_ONLY',snapshot['html'])

    def test_unavailable_processes_are_distinct_from_missing_history(self):
        report=self.report()
        response=self.client.post('/api/processes/pc',headers=self.headers,json={'status':'unavailable','items':[],'report_id':report['report_id'],'report_received':report['report_received']})
        self.assertEqual(response.status_code,200)
        result=self.client.get('/api/history/pc/snapshot',params={'report_id':report['report_id']}).json()
        self.assertFalse(result['processes_available']);self.assertIn('не смог прочитать',result['html'])

    def test_true_extrema_use_original_reports_and_summary_averages_are_not_links(self):
        with a.db() as c:
            identifiers=[]
            for age,cpu,ram in [(300,10,80),(200,95,20),(100,40,30)]:
                identifiers.append(c.execute('INSERT INTO reports VALUES (?,?,?)',('pc',self.now-age,json.dumps({**self.data,'cpu_percent':cpu,'memory_percent':ram}))).lastrowid)
            values=extrema(c,'pc',self.now-3600,self.now)
        self.assertEqual(values['cpu_max']['report_id'],identifiers[1])
        self.assertEqual(values['cpu_min']['report_id'],identifiers[0])
        self.assertEqual(values['ram_max']['report_id'],identifiers[0])
        self.assertEqual(values['ram_min']['report_id'],identifiers[1])
        html=self.client.get('/history/pc?period=1h').text
        self.assertEqual(html.count('class="stat extreme-stat"'),4)
        self.assertIn('Минимум CPU',html);self.assertIn('Минимум RAM',html)
        self.assertIn('data-detail-report="'+str(identifiers[1])+'"',html)
        self.assertIn('<div class="stat"><span>Среднее CPU',html)

    def test_retention_removes_linked_process_history(self):
        report=self.report();self.processes(report)
        old=self.now-(RETENTION_DAYS+1)*86400
        with a.db() as c:
            c.execute('UPDATE reports SET received=? WHERE rowid=?',(old,report['report_id']))
            c.execute('UPDATE process_history SET received=? WHERE report=?',(old,report['report_id']))
            c.execute('DELETE FROM report_maintenance')
            self.assertEqual(cleanup(c,self.now),1)
            self.assertEqual(c.execute('SELECT count(*) FROM process_history').fetchone()[0],0)
