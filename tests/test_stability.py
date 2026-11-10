import json
import sqlite3
import unittest
from server.stability import load,percentage,render
from server.incident_history import SCHEMA,on_report,sync,summary_html


class StabilityTest(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.c.executescript('CREATE TABLE reports(agent TEXT,received REAL,data TEXT);CREATE INDEX reports_agent_time ON reports(agent,received);CREATE TABLE latest_reports(agent TEXT PRIMARY KEY,received REAL,data TEXT);CREATE VIEW current_reports AS SELECT * FROM latest_reports;'+SCHEMA)

    def report(self,at,uptime=1000,cpu=10):
        data={'hostname':'pc','uptime_seconds':uptime,'cpu_percent':cpu,'memory_percent':10,'disks':[],'backups':[],'services':[]}
        encoded=json.dumps(data)
        previous=self.c.execute("SELECT received FROM latest_reports WHERE agent='pc'").fetchone()
        on_report(self.c,'pc',previous,at,encoded)
        self.c.execute("INSERT INTO reports VALUES ('pc',?,?)",(at,encoded))
        self.c.execute("INSERT INTO latest_reports VALUES ('pc',?,?) ON CONFLICT(agent) DO UPDATE SET received=excluded.received,data=excluded.data",(at,encoded))
        return data

    def test_regular_reports_are_full_coverage_and_no_reboot(self):
        for at in range(100,201,10):self.report(at,uptime=at-90)
        info=load(self.c,'pc',100,210)
        self.assertEqual(info['percent'],100)
        self.assertEqual(info['gaps'],[])
        self.assertEqual(info['reboots'],[])

    def test_gap_counts_despite_continuous_os_uptime(self):
        self.report(100,1000);self.report(110,1010);self.report(200,1100)
        info=load(self.c,'pc',100,230)
        self.assertAlmostEqual(info['percent'],100*70/130)
        self.assertEqual(info['gaps'],[[140,200]])
        self.assertEqual(info['reboots'],[])

    def test_prior_record_covers_window_start_and_tail_is_missing(self):
        self.report(90);self.report(150)
        info=load(self.c,'pc',100,200)
        self.assertEqual(info['covered'],50)
        self.assertEqual(info['gaps'],[[120,150],[180,200]])
        self.assertEqual(info['longest'],30)

    def test_before_registration_excluded_and_never_seen_unknown(self):
        self.assertIsNone(load(self.c,'pc',0,300)['percent'])
        self.report(200)
        info=load(self.c,'pc',0,230)
        self.assertEqual(info['start'],200)
        self.assertEqual(info['percent'],100)

    def test_stale_agent_has_zero_and_no_false_full_uptime(self):
        self.report(10)
        info=load(self.c,'pc',100,200)
        self.assertEqual(info['percent'],0)
        self.assertEqual(info['missing'],100)
        self.assertEqual(percentage(99.9999),'99.99%')

    def test_reboot_detected_once_and_bounded_to_period(self):
        self.report(1000,900);self.report(1100,10);self.report(1110,20)
        info=load(self.c,'pc',1000,1140)
        self.assertEqual(len(info['reboots']),1)
        self.assertEqual(info['reboots'][0]['at'],1090)
        self.assertEqual(load(self.c,'pc',1110,1140)['reboots'],[])

    def test_rapid_restart_loop_is_not_hidden_by_clock_tolerance(self):
        self.report(1000,20);self.report(1020,3)
        self.assertEqual(len(load(self.c,'pc',1000,1050)['reboots']),1)

    def test_cpu_incident_opens_once_closes_and_no_fake_recovery_while_offline(self):
        self.report(100,cpu=99);self.report(110,cpu=98)
        row={'id':'pc','received':110,'data':json.dumps({'cpu_percent':98})}
        sync(self.c,[row],400)
        opened=self.c.execute("SELECT * FROM incident_history WHERE category='cpu_percent'").fetchall()
        self.assertEqual(len(opened),1);self.assertIsNone(opened[0]['closed'])
        self.report(410,cpu=10)
        row=self.c.execute("SELECT * FROM incident_history WHERE category='cpu_percent'").fetchone()
        self.assertEqual(row['closed'],410);self.assertEqual(row['resolution'],'recovered')
        connection=self.c.execute("SELECT * FROM incident_history WHERE category='connection'").fetchone()
        self.assertEqual(connection['opened'],290);self.assertEqual(connection['closed'],410)

    def test_outage_recovered_even_when_no_timer_or_page_ran(self):
        self.report(100);self.report(500)
        row=self.c.execute("SELECT * FROM incident_history WHERE category='connection'").fetchone()
        self.assertEqual(row['opened'],280);self.assertEqual(row['closed'],500)
        self.report(510)
        self.assertEqual(self.c.execute("SELECT count(*) FROM incident_history WHERE category='connection'").fetchone()[0],1)

    def test_summary_priorities_stale_resources_not_reused_and_escaped(self):
        rows=[{'id':'bad<script>','received':0,'data':json.dumps({'hostname':'X','cpu_percent':100,'services':[{'name':'sql','status':'stopped'}]})}]
        html=summary_html(rows,200)
        self.assertIn('Критично',html);self.assertIn('bad&lt;script&gt;',html)
        self.assertNotIn('Загрузка CPU',html);self.assertNotIn('sql',html)

    def test_timeline_html_is_bounded(self):
        for at in range(100,10000,60):self.report(at)
        info=load(self.c,'pc',100,10000)
        html=render(info,'pc')
        self.assertLess(len(html),50000)
        self.assertEqual(html.count('title='),96)


class StabilityRoutesTest(unittest.TestCase):
    def test_live_history_and_snapshot_permissions_and_schema(self):
        import test_snapshots as fixtures
        case=fixtures.HistoricalSnapshotsTest();case.setUp()
        try:
            case.data['reboot_history']={'status':'available','events':[{'event_id':41,'record_id':3,'at':100,'source':'Microsoft-Windows-Kernel-Power','kind':'unexpected','message':'Power loss'}]}
            saved=case.report()
            for path in ['/servers/pc?stability=7d','/history/pc?period=7d']:
                response=case.client.get(path);self.assertEqual(response.status_code,200)
                self.assertIn('Доступность по отчётам',response.text)
                self.assertIn('История инцидентов',response.text)
            self.assertEqual(case.client.get('/servers/pc?stability=bad').status_code,400)
            snap=case.client.get('/api/history/pc/snapshot',params={'report_id':saved['report_id']}).json()['html']
            self.assertIn('Power loss',snap)
            self.assertNotIn('Доступность по отчётам',snap)
            case.client.cookies.clear()
            self.assertEqual(case.client.get('/api/history/pc/snapshot',params={'report_id':saved['report_id']}).status_code,401)
        finally:case.doCleanups()
