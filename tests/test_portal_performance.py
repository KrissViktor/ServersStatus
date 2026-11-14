"""Caching must not bypass access checks, stale schema detection or exact coverage."""
import asyncio
import json
import random
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch
import httpx
import test_access_roles as fixtures
from server import app as a
from server.assets import url
from server.stability import load


class PortalPerformanceTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AccessRolesTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.clients['admin']

    def test_existing_database_switches_to_wal_on_process_initialization(self):
        from server.schema_gate import _ready
        with sqlite3.connect(a.DB) as c:
            self.assertEqual(c.execute('PRAGMA journal_mode=DELETE').fetchone()[0],'delete')
        with patch.dict(_ready,{},clear=True):
            with a.db() as c:
                self.assertEqual(c.execute('PRAGMA journal_mode').fetchone()[0],'wal')
                self.assertEqual(c.execute('SELECT COUNT(*) FROM agents').fetchone()[0],1)

    def test_server_page_defers_forecast_history_until_requested(self):
        report={**self.fixture.report,'disks':[{'path':'C:','free_bytes':50,'total_bytes':100,'used_percent':50}]}
        self.assertEqual(self.client.post('/api/report/pc',headers={'Authorization':'Bearer key'},json=report).status_code,200)
        with patch('server.forecast.load_forecasts',side_effect=AssertionError('Page must not scan a week of disk history')):
            response=self.client.get('/servers/pc')
        self.assertEqual(response.status_code,200)
        self.assertIn('data-forecast-url="/servers/pc/forecast"',response.text)
        self.assertIn('data-disk-path="C:"',response.text)
        self.assertIn('/disk_forecast.js',response.text)
        with patch('server.forecast.load_forecasts',return_value={'C:':{'status':'stable'},'removed':{'status':'stable'}}) as measured:
            response=self.client.get('/servers/pc/forecast')
        self.assertEqual(response.status_code,200)
        self.assertEqual(set(response.json()['disks']),{'C:'})
        self.assertIn('Устойчивого уменьшения',response.json()['disks']['C:'])
        self.assertEqual(measured.call_count,1)
        self.assertEqual(response.headers['cache-control'],'no-store')

    def test_forecast_endpoint_enforces_access_and_skips_stale_reports(self):
        with patch('server.forecast.load_forecasts',side_effect=AssertionError('Unauthorized or stale requests must not scan history')):
            self.assertEqual(self.fixture.clients['reader'].get('/servers/pc/forecast').status_code,403)
            self.assertEqual(self.client.get('/servers/missing/forecast').status_code,404)
            report={**self.fixture.report,'disks':[{'path':'C:','free_bytes':50,'total_bytes':100,'used_percent':50}]}
            with a.db() as c:
                c.execute('UPDATE latest_reports SET received=?,data=? WHERE agent=?',(time.time()-200,json.dumps(report),'pc'))
            response=self.client.get('/servers/pc/forecast')
            self.assertEqual(response.status_code,200)
            self.assertIn('Нет связи с агентом',response.json()['disks']['C:'])
            self.client.cookies.clear()
            self.assertEqual(self.client.get('/servers/pc/forecast').status_code,401)

    def test_history_reader_does_not_block_report_commit_or_pages(self):
        # Keep a real SQLite read transaction open, as a long history query does.
        reader=sqlite3.connect(a.DB)
        try:
            reader.execute('BEGIN')
            before=reader.execute('SELECT COUNT(*) FROM reports').fetchone()[0]
            response=self.client.post('/api/report/pc',headers={'Authorization':'Bearer key'},json=self.fixture.report)
            self.assertEqual(response.status_code,200)
            self.assertEqual(self.client.get('/').status_code,200)
            self.assertEqual(self.client.get('/servers/pc').status_code,200)
            self.assertEqual(reader.execute('SELECT COUNT(*) FROM reports').fetchone()[0],before)
        finally:
            reader.rollback();reader.close()
        with a.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM reports').fetchone()[0],before+1)

    def test_slow_report_storage_does_not_freeze_other_http_requests(self):
        entered=threading.Event();release=threading.Event()
        def slow_cleanup(c,now):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Report storage blocked the HTTP event loop')

        async def check():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=a.app),base_url='https://testserver') as client:
                report=asyncio.create_task(client.post('/api/report/pc',headers={'Authorization':'Bearer key'},json=self.fixture.report))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait,2))
                    health=await asyncio.wait_for(client.get('/health'),1)
                    self.assertEqual(health.json(),{'status':'ok'})
                    self.assertFalse(report.done(),'Health must respond while report storage is still pending')
                finally:
                    release.set()
                    result=await report
                self.assertEqual(result.status_code,200)
        with patch.object(a,'cleanup',side_effect=slow_cleanup):
            asyncio.run(check())

    def test_assets_are_versioned_cacheable_and_allowlisted(self):
        asset=url('resource_charts.js')
        with patch('server.access.principal',side_effect=AssertionError('Public assets must not query sessions')),patch.object(a.limiter,'allow',side_effect=AssertionError('Public assets must not consume private request budget')):
            response=self.client.get(asset)
        self.assertEqual(response.status_code,200)
        self.assertIn('immutable',response.headers['cache-control'])
        self.assertIn('text/javascript',response.headers['content-type'])
        self.assertEqual(self.client.get(asset,headers={'If-None-Match':response.headers['etag']}).status_code,304)
        self.assertEqual(self.client.get('/assets/invalid/resource_charts.js').status_code,404)
        self.assertEqual(self.client.get('/assets/invalid/app.py').status_code,404)
        head=self.client.head(asset);self.assertEqual(head.status_code,200);self.assertEqual(head.content,b'')
        self.assertEqual(head.headers['x-content-type-options'],'nosniff')

    def test_summary_matches_full_coverage_with_duplicates_gaps_and_clipped_edges(self):
        rng=random.Random(42)
        with a.db() as c:
            c.execute("DELETE FROM reports WHERE agent='pc'");c.execute("DELETE FROM latest_reports WHERE agent='pc'")
            samples=sorted(set(rng.randrange(100,1000) for _ in range(30)))
            for at in samples:c.execute('INSERT INTO reports VALUES (?,?,?)',('pc',at,json.dumps(self.fixture.report)))
            for start,end in [(0,2000),(300,700),(1100,1400),(samples[3]+3,samples[15]-2)]:
                full=load(c,'pc',start,end);summary=load(c,'pc',start,end,details=False,summary_only=True)
                for key in ('start','end','covered','missing','longest','percent'):self.assertEqual(full[key],summary[key],key)

    def test_initialized_database_does_not_repeat_schema_but_detects_changed_schema(self):
        with patch.object(a,'_initialize_database',wraps=a._initialize_database) as initialize:
            for _ in range(3):
                with a.db() as c:c.execute('SELECT 1')
            self.assertEqual(initialize.call_count,0)
            with a.db() as c:c.execute('DROP TABLE server_groups')
            with a.db() as c:self.assertIsNotNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='server_groups'").fetchone())
            self.assertEqual(initialize.call_count,1)

    def test_one_server_page_does_not_compute_other_agents_history(self):
        with a.db() as c:c.execute("INSERT INTO agents VALUES ('other','unused')")
        with patch('server.stability.load',wraps=load) as measured:
            response=self.client.get('/servers/pc')
        self.assertEqual(response.status_code,200)
        self.assertTrue(all(call.args[1]=='pc' for call in measured.call_args_list))

    def test_colored_coverage_links_to_a_bounded_read_only_timeline(self):
        response=self.client.get('/servers/pc?stability=24h')
        self.assertIn('/timeline/pc?start=',response.text)
        now=time.time()
        with a.db() as c:
            c.execute('INSERT INTO incident_history(key,agent,category,opened,last_seen,message) VALUES (?,?,?,?,?,?)',('before:pc','pc','service',now-400,now-200,'ONGOING-SQL'))
        response=self.client.get('/timeline/pc',params={'start':now-300,'end':now-100})
        self.assertEqual(response.status_code,200);self.assertIn('Продолжающаяся проблема',response.text);self.assertIn('ONGOING-SQL',response.text)
        self.assertEqual(self.client.get('/timeline/pc',params={'start':'nan','end':now}).status_code,400)
        self.assertEqual(self.fixture.clients['reader'].get('/timeline/pc').status_code,403)

    def test_html_uses_shared_assets_and_gzip_without_private_cache(self):
        response=self.client.get('/',headers={'Accept-Encoding':'gzip'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers.get('content-encoding'),'gzip')
        self.assertNotIn('<style>',response.text)
        self.assertIn('/assets/',response.text)
        self.assertNotIn('public',response.headers.get('cache-control',''))

    def test_overview_memory_details_are_loaded_for_the_same_exact_bucket(self):
        start=(int(time.time())//30)*30-60
        with a.db() as c:
            for offset,value in [(1,25),(11,50),(21,75)]:
                report={**self.fixture.report,'cpu_percent':value,'memory_percent':value,'system':{'memory_total_bytes':16*1024**3,'memory_used_bytes':value/100*16*1024**3}}
                c.execute('INSERT INTO reports VALUES (?,?,?)',('pc',start+offset,json.dumps(report)))
        points=a.server_rows('pc')[0]['sparkline']
        compact=next(p for p in points if p['first']==start+1)
        self.assertEqual(compact['samples'],3);self.assertNotIn('ram_used_bytes',compact)
        response=self.client.get('/api/history/pc/resources',params={'overview':True,'start':start,'end':start+30})
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['bucket'],30)
        detail=response.json()['points'][0]
        self.assertEqual((detail['first'],detail['last']),(compact['first'],compact['last']))
        self.assertEqual(detail['ram_used_bytes'],8*1024**3)
        self.assertEqual(detail['ram_total_bytes'],16*1024**3)
