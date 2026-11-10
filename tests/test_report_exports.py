import csv
import io
import json
import unittest
import xml.etree.ElementTree as ET
from pypdf import PdfReader
import test_snapshots as fixtures
from server import app as a
from server.report_exports import csv_bytes,xml_bytes


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.HistoricalSnapshotsTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.client;self.fixture.report()

    def test_all_formats_real_pdf_and_selected_servers_no_secrets(self):
        for format in ['json','xml','csv','pdf']:
            response=self.client.get('/export/compare',params={'agents':'pc','period':'1h','format':format})
            self.assertEqual(response.status_code,200,response.text[:100] if format!='pdf' else '')
            self.assertIn('attachment;',response.headers['content-disposition']);self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertNotIn(b'SECRET-IDENTITY',response.content)
            if format=='json':
                data=response.json();self.assertEqual([row['id'] for row in data['servers']],['pc']);self.assertEqual(data['timezone'],'Europe/Moscow')
                self.assertIn('chart_points',data['servers'][0]);self.assertEqual(data['servers'][0]['sample_count'],1)
            elif format=='xml':self.assertEqual(ET.fromstring(response.content).tag,'serversstatus_report')
            elif format=='csv':
                self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
                rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';'))
                self.assertEqual(rows[2][0],'server');self.assertEqual(len(rows[0]),len(rows[2]))
            else:
                self.assertTrue(response.content.startswith(b'%PDF-'))
                reader=PdfReader(io.BytesIO(response.content));text='\n'.join(page.extract_text() for page in reader.pages)
                self.assertIn('Сравнение серверов',text);self.assertIn('Доступность',text)

    def test_csv_formula_and_xml_escaping(self):
        report=self.client.get('/export/compare?format=json&agents=pc').json()
        report['servers'][0]['name']=' =HYPERLINK("https://example.com")'
        csv_data=csv_bytes(report).decode('utf-8-sig');rows=list(csv.reader(io.StringIO(csv_data),delimiter=';'))
        self.assertTrue(rows[2][4].startswith("'"))
        report['servers'][0]['equipment_changes']=[{'before':[{'fields':{'x & y':'<script>\x01 & данные'}}]}]
        root=ET.fromstring(xml_bytes(report));self.assertIn('<script> & данные',''.join(root.itertext()))

    def test_scope_errors_daily_and_roles(self):
        self.assertEqual(self.client.get('/export/compare?format=exe').status_code,400)
        self.assertEqual(self.client.get('/export/compare?agents=missing').status_code,400)
        self.assertEqual(self.client.get('/export/daily?format=json&day=2099-01-01').status_code,400)
        response=self.client.get('/export/daily?format=json');self.assertEqual(response.status_code,200);self.assertEqual(response.json()['kind'],'daily')
        self.assertEqual(self.client.get('/export/compare?format=json&group=bad').status_code,400)
        self.client.cookies.clear();self.assertEqual(self.client.get('/export/daily?format=pdf').status_code,401)
        with a.db() as c:
            c.execute("INSERT INTO users VALUES ('viewer',?,?)",('00'*16,'0'*128));c.execute("INSERT INTO user_roles VALUES ('viewer','viewer',1)");c.execute("UPDATE session_users SET name='viewer'")
        self.client.cookies.set('session','test');self.assertEqual(self.client.get('/export/daily?format=json').status_code,403)
        self.assertEqual(self.client.get('/portal-health').status_code,403)
