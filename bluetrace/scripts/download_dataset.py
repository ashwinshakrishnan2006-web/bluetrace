"""Download the pinned CC BY 4.0 SAR image/mask dataset; verify LFS SHA256."""
from pathlib import Path
import concurrent.futures as cf
import hashlib, json, urllib.request, time
ROOT = Path(__file__).resolve().parents[1] / 'data/public'
REPO = 'Garcia-INPE/oilspill-detection-dataset'
COMMIT = '1b9a62c30a9da9698eb470562aa976f9bd1e8fc3'
def get(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=45) as r: return r.read()
        except Exception:
            if attempt == 2: raise
            time.sleep(1)
def download(path):
    dest = ROOT / path; dest.parent.mkdir(parents=True, exist_ok=True)
    raw = get(f'https://raw.githubusercontent.com/{REPO}/{COMMIT}/{path}')
    if raw.startswith(b'version https://git-lfs'):
        expected = raw.decode().split('oid sha256:')[1].splitlines()[0]
        data = dest.read_bytes() if dest.exists() else get(f'https://media.githubusercontent.com/media/{REPO}/{COMMIT}/{path}')
        if hashlib.sha256(data).hexdigest() != expected: raise ValueError('LFS hash mismatch: ' + path)
    else: data = raw
    dest.write_bytes(data)
    return {'path':path, 'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    tree = json.loads(get(f'https://api.github.com/repos/{REPO}/git/trees/{COMMIT}?recursive=1'))
    paths = [x['path'] for x in tree['tree'] if x['type']=='blob' and (x['path'].startswith(('IMAGES/IMG-RGB/','IMAGES/LABELS-1D/','splits/')) or x['path'] in ['LICENSE','CITATION.cff','DATASET_CARD.md'])]
    results=[]
    with cf.ThreadPoolExecutor(max_workers=16) as pool:
        for i,r in enumerate(pool.map(download,paths)):
            results.append(r)
            if i % 40 == 0: print(f'Downloaded {i+1}/{len(paths)}',flush=True)
    (ROOT/'provenance.json').write_text(json.dumps({'repository':f'https://github.com/{REPO}','commit':COMMIT,'files':results},indent=2))
    print(f'Complete: {len(results)} files; {sum(r["bytes"] for r in results)/1e6:.1f} MB',flush=True)
if __name__=='__main__': main()
