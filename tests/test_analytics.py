import json
import sqlite3
import unittest
from server.forecast import predict
from server.io_history import samples,chart
from server.history import stamp

class AnalyticsTest(unittest.TestCase):
    def test_forecast_linear_and_insufficient_and_resize(self):
        gb=1024**3
        rows=[{'timestamp':i*3600,'total':100*gb,'free':(80-i/24*10)*gb} for i in range(49)]
        result=predict(rows)
        self.assertEqual(result['status'],'estimated')
        self.assertAlmostEqual(result['days'],6)
        self.assertEqual(predict(rows[:10])['status'],'insufficient')
        resized=rows+[{'timestamp':50*3600,'total':200*gb,'free':180*gb}]
        self.assertEqual(predict(resized)['status'],'insufficient')
        stable=[dict(row,free=80*gb) for row in rows]
        self.assertEqual(predict(stable)['status'],'stable')

    def test_io_rates_are_not_clipped_to_one_hundred(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
        self.addCleanup(c.close)
        c.execute('CREATE TABLE reports(agent TEXT,received REAL,data TEXT)')
        for timestamp,value in [(1000,1024**2),(1060,2*1024**2),(1400,3*1024**2)]:
            c.execute('INSERT INTO reports VALUES (?,?,?)',('pc',timestamp,json.dumps({'network':[{'name':'Ethernet','receive_bytes_per_second':value}]})))
        rows=samples(c,'pc','network','Ethernet','receive_bytes_per_second',900,1500,60)
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[-1]['has_gap'],1)
        markup=chart(rows,'Сеть',900,1500)
        self.assertIn('3.0 Мб/с',markup)
        self.assertNotIn('100%',markup)
        self.assertEqual(markup.count('stroke-width="2"'),1)
