import unittest, tempfile, threading, json, base64, sys, csv, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from analysis import *
from scripts.train_model import counts, metrics

class AnalysisTests(unittest.TestCase):
    def test_01_invalid_image(self):
        with self.assertRaises(ValueError):decode_image('not an image')
    def test_02_bad_coordinates(self):
        with self.assertRaises(ValueError):geo_config({'bounds':{'west':82,'east':81,'north':13,'south':12}})
    def test_03_nan_rejected(self):
        with self.assertRaises(ValueError):num(float('nan'),'test',0,1)
    def test_04_timezone_required(self):
        with self.assertRaises(ValueError):stamp('2026-09-18T06:40:00')
    def test_05_ais_conflict(self):
        with self.assertRaises(ValueError):parse_ais('mmsi,timestamp,latitude,longitude\n900000001,2026-09-18T00:00:00Z,12,81\n900000001,2026-09-18T00:00:00Z,13,81')
    def test_06_ais_sort_and_deduplicate(self):
        s='mmsi,timestamp,latitude,longitude\n900000001,2026-09-18T01:00:00Z,12,81\n900000001,2026-09-18T00:00:00Z,12,81\n900000001,2026-09-18T00:00:00Z,12,81'
        t=parse_ais(s)['900000001'];self.assertEqual(len(t),2);self.assertLess(t[0]['time'],t[1]['time'])
    def track(self,minutes,lon=81.001):
        return [{'time':'2026-09-18T00:00:00Z','latitude':12,'longitude':81},{'time':(stamp('2026-09-18T00:00:00Z')+timedelta(minutes=minutes)).isoformat(),'latitude':12,'longitude':lon}]
    def test_07_interpolation_gap(self):self.assertIsNone(interpolate(self.track(60),stamp('2026-09-18T00:15:00Z')))
    def test_08_interpolation_speed(self):self.assertIsNone(interpolate(self.track(20,85),stamp('2026-09-18T00:10:00Z')))
    def test_09_interpolation_arithmetic(self):self.assertAlmostEqual(interpolate(self.track(20),stamp('2026-09-18T00:10:00Z'))[0],81.0005)
    def test_10_metrics_arithmetic(self):
        m=metrics([2,1,1,6]);self.assertEqual(m['iou'],.5);self.assertAlmostEqual(m['f1'],2/3)
    def test_11_empty_track_no_extrapolation(self):self.assertIsNone(interpolate(self.track(20),stamp('2026-09-18T01:00:00Z')))
    def test_12_split_integrity(self):
        groups=[];ids=[]
        for s in ['train','val','test']:
            rows=list(csv.DictReader((ROOT/f'data/public/splits/{s}.csv').read_text().splitlines()));groups.append({r['sample_id'].split('_TILE')[0] for r in rows});ids.extend(r['sample_id'] for r in rows)
            for r in rows:
                with Image.open(ROOT/'data/public'/r['image_path']) as im, Image.open(ROOT/'data/public'/r['mask_path']) as mask:
                    self.assertEqual(im.size,mask.size);self.assertEqual(mask.mode,'L');self.assertLessEqual(set(np.unique(mask)),{0,1,2})
        self.assertEqual(len(set(ids)),173);self.assertFalse(groups[0]&groups[1] or groups[0]&groups[2] or groups[1]&groups[2])
    def test_13_checksums(self):
        j=json.loads((ROOT/'data/public/provenance.json').read_text())
        for f in j['files']:self.assertEqual(hashlib.sha256((ROOT/'data/public'/f['path']).read_bytes()).hexdigest(),f['sha256'])

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();server.RUNTIME=Path(cls.temp.name);cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);threading.Thread(target=cls.http.serve_forever,daemon=True).start();cls.url=f'http://127.0.0.1:{cls.http.server_port}'
    @classmethod
    def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.temp.cleanup()
    def request(self,path,data=None,headers=None):
        req=Request(self.url+path,json.dumps(data).encode() if data is not None else None,headers=headers or {})
        with urlopen(req) as r:return r.status,r.read(),r.headers
    def test_14_full_workflow(self):
        status,raw,_=self.request('/api/demo',{});self.assertEqual(status,201);r=json.loads(raw);ident=r['id'];self.assertGreater(len(r['regions']),0);self.assertGreater(len(r['sources']),0);self.assertGreater(len(r['candidates']),0)
        self.assertEqual(json.loads(self.request('/api/incidents/'+ident)[1])['id'],ident)
        self.assertEqual(json.loads(self.request('/api/incidents/'+ident+'/geojson')[1])['type'],'FeatureCollection')
        self.assertEqual(json.loads(self.request('/api/incidents/'+ident+'/report')[1])['id'],ident)
        self.assertIn(ident,[v['id'] for v in json.loads(self.request('/api/incidents')[1])])
        for url in r['assets'].values():self.assertTrue(self.request(url)[1].startswith(b'\x89PNG'))
        self.request('/api/incidents/'+ident+'/delete',{})
        self.assertFalse((server.RUNTIME/ident).exists())
        with self.assertRaises(HTTPError) as e:self.request('/api/incidents/'+ident)
        self.assertEqual(e.exception.code,404)
    def test_15_real_image_only(self):
        s=json.loads(self.request('/api/dataset/sample')[1]);p={'name':'Test real SAR','observation':s['observation'],'image_base64':s['image_base64']}
        r=json.loads(self.request('/api/incidents',p)[1]);self.assertFalse(r['sources']);self.assertFalse(r['candidates']);self.assertEqual(r['model'],'trained')
    def test_16_cross_origin_denied(self):
        with self.assertRaises(HTTPError) as e:self.request('/api/demo',{}, {'Origin':'https://example.org'})
        self.assertEqual(e.exception.code,403)
    def test_17_host_denied(self):
        with self.assertRaises(HTTPError) as e:self.request('/api/health',headers={'Host':'attacker.example'})
        self.assertEqual(e.exception.code,403)
    def test_18_static_delivery(self):
        for path in ['/','/app.js','/style.css']:
            status,raw,headers=self.request(path);self.assertEqual(status,200);self.assertGreater(len(raw),100);self.assertIn('Content-Security-Policy',headers)
    def test_19_bad_request_no_partial_save(self):
        before=json.loads(self.request('/api/incidents')[1])
        with self.assertRaises(HTTPError) as e:self.request('/api/incidents',{'name':'bad','observation':'2026-09-18T06:40:00Z','image_base64':'nonsense'})
        self.assertEqual(e.exception.code,400);self.assertEqual(before,json.loads(self.request('/api/incidents')[1]))
    def test_20_busy_response(self):
        with server.LOCK:
            with self.assertRaises(HTTPError) as e:self.request('/api/demo',{})
        self.assertEqual(e.exception.code,429)
    def test_21_path_traversal_denied(self):
        with self.assertRaises(HTTPError) as e:self.request('/assets/../../server.py')
        self.assertEqual(e.exception.code,404)
    def test_22_metrics_endpoint(self):
        r=json.loads(self.request('/api/metrics')[1]);self.assertEqual(r['split_counts']['test'],22);self.assertEqual(sum(r['test'][k] for k in ['tp','fp','fn','tn']),660000)
if __name__=='__main__':unittest.main(verbosity=2)
