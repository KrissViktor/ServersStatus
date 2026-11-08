import json
import sqlite3
import unittest
from server.forecast import load_forecasts, forecast_html
from server.history import load_history, chart
from server.task_graph import graph


class ForecastMemoryTest(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE reports(agent TEXT,received REAL,data TEXT)')
        self.db.execute('CREATE INDEX reports_resource_metrics ON reports(agent,received)')

    def test_three_disks_keep_independent_trends_and_new_disk_visible(self):
        for hour in range(49):
            disks=[{'path':path,'total_bytes':100*1024**3,'free_bytes':free*1024**3}
                   for path,free in [('C:',80-hour*.1),('D:',20-hour*.3),('E:',40+hour*.1)]]
            self.db.execute('INSERT INTO reports VALUES (?,?,?)',('pc',hour*3600,json.dumps({'disks':disks})))
        forecasts=load_forecasts(self.db,'pc',48*3600)
        self.assertEqual(set(forecasts),{'C:','D:','E:'})
        self.assertEqual(forecasts['C:']['status'],'estimated')
        self.assertEqual(forecasts['D:']['status'],'estimated')
        self.assertEqual(forecasts['E:']['status'],'stable')
        self.assertAlmostEqual(forecasts['D:']['bytes_per_day']/forecasts['C:']['bytes_per_day'],3)
        current=[{**d,'used_percent':100-d['free_bytes']/d['total_bytes']*100} for d in disks]
        current.append({'path':'F:','free_bytes':1,'total_bytes':100,'used_percent':99})
        html=forecast_html(forecasts,disks=current)
        self.assertEqual(html.count('class="forecast-disk"'),4)
        for label in ('C:','D:','E:','F:','До 95%','До 98%','Темп заполнения','часовых точек','Недостаточно истории'):
            self.assertIn(label,html)
        self.assertNotIn('До 95%',forecast_html(forecasts,stale=True,disks=current))

    def test_ram_tooltips_use_historical_bytes_and_handle_legacy_reports(self):
        for timestamp,percent,total,used in [(1000,25,16,4),(1020,50,16,8),(1300,50,32,16)]:
            data={'cpu_percent':1,'memory_percent':percent,'system':{'memory_total_bytes':total*1024**3,'memory_used_bytes':used*1024**3}}
            self.db.execute('INSERT INTO reports VALUES (?,?,?)',('pc',timestamp,json.dumps(data)))
        points=load_history(self.db,'pc',900,1400,300)
        self.assertEqual(points[0]['ram_used_bytes'],6*1024**3)
        self.assertEqual(points[0]['ram_used_peak_bytes'],8*1024**3)
        html=chart(points,'ram','RAM',900,1400,'blue')
        self.assertIn('занято 6.0 Гб из 16.0 Гб',html)
        self.assertIn('занято 16.0 Гб из 32.0 Гб',html)
        self.assertIn('пик объёма: 8.0 Гб',html)
        self.assertIn('занято 4.0 Гб',graph([{'timestamp':1000,'ram':25,'ram_used_bytes':4*1024**3}], 'ram',1100))
        self.assertIn('объём RAM недоступен',graph([{'timestamp':1000,'ram':25}], 'ram',1100))
