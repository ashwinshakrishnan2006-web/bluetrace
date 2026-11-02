"""Local single-analyst HTTP server. Do not expose directly to the Internet."""
import argparse, base64, json, mimetypes, os, re, shutil, sqlite3, threading, uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from analysis import ROOT, analyze
RUNTIME=Path(os.environ.get('BLUETRACE_RUNTIME',ROOT/'runtime'))
LOCK=threading.Lock()
def db():
    RUNTIME.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(RUNTIME/'bluetrace.db'); c.execute('CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY,name TEXT NOT NULL,created TEXT NOT NULL,result TEXT NOT NULL)');return c

def demo_payload(): return json.loads((ROOT/'data/demo/request.json').read_text())
def save_incident(p):
    ident=uuid.uuid4().hex; asset=RUNTIME/ident
    try:
        r=analyze(p,asset); r.update(id=ident,created=datetime.now(timezone.utc).isoformat(),assets={k:f'/assets/{ident}/{k}.png' for k in ['image','mask','overlay']})
        with db() as c: c.execute('INSERT INTO incidents VALUES (?,?,?,?)',(ident,r['name'],r['created'],json.dumps(r)))
        return r
    except Exception:
        shutil.rmtree(asset,ignore_errors=True);raise

def get_incident(ident):
    with db() as c: row=c.execute('SELECT result FROM incidents WHERE id=?',(ident,)).fetchone()
    if not row: raise FileNotFoundError('Incident not found.')
    return json.loads(row[0])

class Handler(BaseHTTPRequestHandler):
    def send(self,status,data,mime='application/json',filename=None):
        if not isinstance(data,bytes): data=json.dumps(data,allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if filename:self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers();self.wfile.write(data)
    def safe_origin(self):
        host=self.headers.get('Host','')
        if host not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}:return False
        origin=self.headers.get('Origin')
        return not origin or origin in {f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}
    def do_GET(self):
        if not self.safe_origin():return self.send(403,{'error':'Local same-origin requests only.'})
        p=urlparse(self.path).path
        try:
            if p=='/api/health':return self.send(200,{'status':'ok','model_ready':(ROOT/'models/segmenter.joblib').exists(),'mode':'local single analyst','dataset_pairs':len(list((ROOT/'data/public/IMAGES/IMG-RGB').glob('*.png')))})
            if p=='/api/metrics':return self.send(200,json.loads((ROOT/'reports/metrics.json').read_text()))
            if p=='/api/incidents':
                with db() as c: rows=c.execute('SELECT id,name,created FROM incidents ORDER BY created DESC').fetchall()
                return self.send(200,[dict(zip(['id','name','created'],r)) for r in rows])
            m=re.fullmatch(r'/api/incidents/([a-f0-9]{32})(/(report|geojson))?',p)
            if m:
                r=get_incident(m[1]); kind=m[3]
                return self.send(200,r['geojson'] if kind=='geojson' else r,filename=(f'bluetrace-{m[1]}.{ "geojson" if kind=="geojson" else "json"}' if kind else None))
            if p=='/api/dataset/sample':
                import csv
                row=next(csv.DictReader((ROOT/'data/public/splits/test.csv').read_text().splitlines()))
                return self.send(200,{'sample_id':row['sample_id'],'image_base64':base64.b64encode((ROOT/'data/public'/row['image_path']).read_bytes()).decode(),'observation':'2020-01-01T00:00:00Z','note':'Public SAR test sample. Timestamp is a placeholder; do image-only screening. Do not associate with fictional AIS.'})
            m=re.fullmatch(r'/assets/([a-f0-9]{32})/(image|mask|overlay)\.png',p)
            if m:return self.send(200,(RUNTIME/m[1]/(m[2]+'.png')).read_bytes(),'image/png')
            files={'/':'index.html','/index.html':'index.html','/style.css':'style.css','/app.js':'app.js'}
            if p in files:
                path=ROOT/'static'/files[p];return self.send(200,path.read_bytes(),mimetypes.guess_type(str(path))[0] or 'text/plain')
            raise FileNotFoundError('Not found.')
        except FileNotFoundError:return self.send(404,{'error':'Not found.'})
        except Exception as e:
            print(type(e).__name__,str(e));return self.send(500,{'error':'Unable to load resource. Check server logs.'})
    def do_POST(self):
        if not self.safe_origin():return self.send(403,{'error':'Local same-origin requests only.'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<0 or length>15_000_000:return self.send(413,{'error':'Request too large.'})
            self.connection.settimeout(30)
            raw=self.rfile.read(length)
            p=urlparse(self.path).path
            m=re.fullmatch(r'/api/incidents/([a-f0-9]{32})/delete',p)
            if m:
                with LOCK:
                    get_incident(m[1])
                    with db() as c:c.execute('DELETE FROM incidents WHERE id=?',(m[1],))
                    shutil.rmtree(RUNTIME/m[1],ignore_errors=True)
                return self.send(200,{'deleted':True})
            if p not in ('/api/incidents','/api/demo'):return self.send(404,{'error':'Not found.'})
            if not LOCK.acquire(blocking=False):return self.send(429,{'error':'Another analysis is running. Retry shortly.'})
            try:
                payload=demo_payload() if p=='/api/demo' else json.loads(raw)
                result=save_incident(payload)
                return self.send(201,result)
            finally:LOCK.release()
        except FileNotFoundError:return self.send(404,{'error':'Not found.'})
        except (ValueError,TypeError,KeyError) as e:return self.send(400,{'error':str(e)})
        except Exception as e:
            print(type(e).__name__,str(e));return self.send(500,{'error':'Analysis failed. Check server logs.'})
    def log_message(self,fmt,*args):print(fmt%args)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8000);args=parser.parse_args()
    db().close();print(f'Bluetrace running at http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
