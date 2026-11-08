import json
from pathlib import Path
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from server import app as a
from server.history import history_page


class DrilldownTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr,a,'DB',a.DB);a.DB=str(Path(self.tmp.name)/'db.sqlite3')
        self.client=TestClient(a.app,base_url='https://testserver');self.client.cookies.set('session','test')
        self.now=time.time();self.start=self.now-15000
        from server.security import limiter
        limiter.reset()
        with a.db() as c:
            c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest('test'),self.now+3600))
            c.execute("INSERT OR IGNORE INTO users VALUES ('admin',?,?)",('00'*16,'0'*128))
            c.execute("INSERT INTO session_users VALUES (?,'admin')",(a.digest('test'),))
            c.execute('INSERT INTO agents VALUES (?,?)',('pc',a.digest('key')))
            c.execute('INSERT INTO agents VALUES (?,?)',('other',a.digest('other-key')))
            for i in range(1500):
                data={'cpu_percent':i%100,'memory_percent':25,'system':{'memory_total_bytes':16*1024**3,'memory_available_bytes':12*1024**3},'network':[{'name':'Ethernet','receive_bytes_per_second':i},{'name':'Other NIC','receive_bytes_per_second':90000}]}
                c.execute('INSERT INTO reports VALUES (?,?,?)',('pc',self.start+i*10,json.dumps(data)))
                if i==750:c.execute('INSERT INTO reports VALUES (?,?,?)',('other',self.start+i*10,json.dumps({'cpu_percent':9999})))

    def get(self,**params):
        return self.client.get('/api/history/pc/detail',params={'center':self.start+7500,**params})

    def test_original_bucket_zoom_limit_and_isolation(self):
        first,last=self.start+7400,self.start+7690
        data=self.get(count=30,first=first,last=last).json()
        self.assertEqual(len(data['points']),30)
        self.assertEqual(data['points'][0]['timestamp'],first)
        self.assertEqual(data['points'][-1]['timestamp'],last)
        for count in (30,90,270,810,900):
            response=self.get(count=count)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['count'],count)
            points=response.json()['points']
            self.assertEqual(points,sorted(points,key=lambda p:p['timestamp']))
            self.assertTrue(all(p['value']<100 for p in points))
            self.assertNotIn('data',points[0])
        self.assertEqual(self.get(count=901).status_code,422)
        self.assertEqual(self.get(count=0).status_code,422)
        self.assertEqual(self.get(center=float('nan')).status_code,400)
        self.assertEqual(self.get(metric='arbitrary.sql').status_code,400)
        self.assertEqual(self.get(first=20,last=10).status_code,400)

    def test_authentication_edges_device_and_ram(self):
        anonymous=TestClient(a.app,base_url='https://testserver')
        self.assertEqual(anonymous.get('/api/history/pc/detail',params={'center':self.now}).status_code,401)
        self.assertEqual(self.client.get('/api/history/missing/detail',params={'center':self.now}).status_code,404)
        data=self.get(center=self.start,count=900).json()
        self.assertEqual(data['count'],900)
        self.assertEqual(data['points'][0]['timestamp'],self.start)
        ram=self.get(metric='ram',count=30).json()
        self.assertEqual(ram['unit'],'%')
        self.assertEqual(ram['points'][0]['ram_used_bytes'],4*1024**3)
        nic=self.get(metric='network.receive_bytes_per_second',name='Other NIC').json()
        self.assertTrue(all(p['value']==90000 for p in nic['points']))
        missing=self.get(metric='disk_io.read_iops',name='absent').json()
        self.assertTrue(all(p['value'] is None for p in missing['points']))

    def test_ram_summary_uses_weighted_sizes_and_peak(self):
        points=[{'timestamp':1000,'first':1000,'last':1010,'samples':2,'cpu':10,'cpu_peak':10,'ram':25,'ram_peak':25,'ram_used_bytes':4*1024**3,'ram_used_peak_bytes':5*1024**3,'ram_size_samples':2,'has_gap':0},
                {'timestamp':1100,'first':1100,'last':1100,'samples':1,'cpu':10,'cpu_peak':10,'ram':50,'ram_peak':50,'ram_used_bytes':10*1024**3,'ram_used_peak_bytes':12*1024**3,'ram_size_samples':1,'has_gap':0}]
        html=history_page('pc',points,'1h',900,1200)
        self.assertIn('Среднее RAM',html);self.assertIn('Пик RAM',html)
        self.assertIn('>6.0 Гб</small>',html);self.assertIn('>12.0 Гб</small>',html)
        self.assertIn('data-detail-count="2"',html)
