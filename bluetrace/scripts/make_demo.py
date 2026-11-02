"""Independent synthetic geographic fixture, never a real attribution claim."""
import sys, json, csv, base64
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analysis import ROOT
import numpy as np
from PIL import Image
from datetime import datetime,timezone,timedelta
out=ROOT/'data/demo';out.mkdir(exist_ok=True)
rng=np.random.default_rng(71);y,x=np.mgrid[:300,:400]
im=np.clip(155+rng.normal(0,17,(300,400)),0,255)
slick=((x-218)/75)**2+((y-130-.2*(x-218))/18)**2<1
im[slick]=np.clip(42+rng.normal(0,7,slick.sum()),0,255)
Image.fromarray(im.astype('uint8')).save(out/'synthetic_sar.png')
Image.fromarray((slick*255).astype('uint8')).save(out/'synthetic_mask.png')
obs=datetime(2026,9,18,6,40,tzinfo=timezone.utc)
rows=[]
for m,name,offset in [('900000001','FICTIONAL Aster',0),('900000002','FICTIONAL Boreal',.06),('900000003','FICTIONAL Coral',-.09)]:
    for n in range(19):
        age=4.5-n/4;t=obs-timedelta(hours=age)
        # Aster passes the injected slick backtrack at two hours.
        rows.append({'mmsi':m,'name':name,'timestamp':t.isoformat(),'latitude':12.513+offset,'longitude':81.0545-.2*age*3600/(111320*np.cos(np.deg2rad(12.513)))})
with (out/'fictional_ais.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
p={'name':'Synthetic spill and fictional vessels','observation':obs.isoformat(),'image_base64':base64.b64encode((out/'synthetic_sar.png').read_bytes()).decode(),'ais_csv':(out/'fictional_ais.csv').read_text(),'bounds':{'west':81.,'east':81.1,'south':12.47,'north':12.57},'current_east':.2,'current_north':0,'wind_east':0,'wind_north':0,'windage':.03,'uncertainty':.15,'age_min':1,'age_max':4,'model':'dark','notes':'SYNTHETIC FIXTURE. Fictional MMSIs and constant conditions. Use only for software demonstration. Not an observed incident.'}
(out/'request.json').write_text(json.dumps(p,indent=2))
(out/'environment.json').write_text(json.dumps({k:v for k,v in p.items() if k not in ['image_base64','ais_csv']},indent=2))
print('Demo generated: image, ground truth mask, 57 fictional AIS records, environment and request')
