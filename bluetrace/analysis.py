"""Image segmentation and transparent, non-causal vessel association."""
import base64, csv, io, math
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from scipy import ndimage as ndi
import joblib
ROOT=Path(__file__).resolve().parent
MODEL=None
WORK_SIZE=(200,150)

def stamp(value):
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None: raise ValueError()
        return dt.astimezone(timezone.utc)
    except (ValueError,TypeError): raise ValueError('Use an ISO timestamp with timezone, for example 2026-09-18T06:40:00Z.')

def num(value,name,low,high):
    try: v=float(value)
    except (ValueError,TypeError): raise ValueError(f'{name} must be numeric.')
    if not math.isfinite(v) or not low<=v<=high: raise ValueError(f'{name} must be between {low} and {high}.')
    return v

def features(image):
    g=np.asarray(image.convert('L'),dtype=np.float32)/255
    out=[g]
    for s in (2,5,11):
        m=ndi.uniform_filter(g,size=s,mode='reflect')
        sd=np.sqrt(np.maximum(ndi.uniform_filter(g*g,size=s,mode='reflect')-m*m,0))
        out += [m,sd,g-m]
    out += [np.hypot(ndi.sobel(g,0),ndi.sobel(g,1)),np.full_like(g,np.mean(g))]
    return np.stack(out,-1).reshape(-1,12)

def load_model():
    global MODEL
    if MODEL is None:
        path=ROOT/'models/segmenter.joblib'
        if not path.exists(): raise ValueError('Model missing. Run python scripts/train_model.py first.')
        MODEL=joblib.load(path) # Only the locally shipped/trained model is loaded, never an upload.
    return MODEL

def segment(image,mode='trained'):
    im=ImageOps.exif_transpose(image).convert('RGB').resize(WORK_SIZE,Image.Resampling.BILINEAR)
    if mode=='trained':
        m=load_model(); probability=m['estimator'].predict_proba(features(im))[:,1].reshape(WORK_SIZE[1],WORK_SIZE[0]); mask=probability>=m['threshold']
    elif mode=='dark':
        g=np.asarray(im.convert('L')); probability=1-g/255.; mask=g<np.percentile(g,18)
    else: raise ValueError('Unknown model. Choose trained or dark.')
    return im,mask

def decode_image(encoded):
    if not isinstance(encoded,str) or len(encoded)>12_000_000: raise ValueError('Image must be a base64 PNG/JPEG below 8 MB.')
    try:
        raw=base64.b64decode(encoded,validate=True)
        if len(raw)>8_000_000: raise ValueError()
        im=Image.open(io.BytesIO(raw))
        if im.format not in ('PNG','JPEG') or im.width*im.height>16_000_000 or min(im.size)<16: raise ValueError()
        im.load(); return im
    except Exception as e: raise ValueError('Invalid image. Use PNG/JPEG, at least 16 pixels per side and at most 16 megapixels.') from e

def parse_ais(text):
    if not text: return {}
    if not isinstance(text,str) or len(text)>2_000_000: raise ValueError('AIS CSV must be below 2 MB.')
    reader=csv.DictReader(io.StringIO(text))
    if not {'mmsi','timestamp','latitude','longitude'}.issubset(reader.fieldnames or []): raise ValueError('AIS CSV needs mmsi,timestamp,latitude,longitude headers.')
    tracks={}; seen={}
    for i,row in enumerate(reader):
        if i>=20000: raise ValueError('AIS CSV exceeds 20,000 rows.')
        m=row['mmsi'].strip()
        if len(m)!=9 or not m.isdigit(): raise ValueError(f'AIS row {i+2}: MMSI must have nine digits.')
        t=stamp(row['timestamp']); lat=num(row['latitude'],'latitude',-85,85); lon=num(row['longitude'],'longitude',-180,180)
        key=(m,t.isoformat())
        if key in seen:
            if seen[key]!=(lat,lon): raise ValueError('Conflicting positions for the same vessel and timestamp.')
            continue
        seen[key]=(lat,lon)
        tracks.setdefault(m,[]).append({'time':t.isoformat(),'latitude':lat,'longitude':lon,'name':str(row.get('name') or m)[:100]})
    for track in tracks.values(): track.sort(key=lambda x:x['time'])
    return tracks

def distance(a,b):
    p1,p2=math.radians(a[1]),math.radians(b[1]); dp=p2-p1; dl=math.radians(b[0]-a[0])
    h=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 6371000*2*math.asin(math.sqrt(min(1,max(0,h))))

def interpolate(track,time):
    for r in track:
        if stamp(r['time'])==time: return [r['longitude'],r['latitude']]
    for a,b in zip(track,track[1:]):
        t0,t1=stamp(a['time']),stamp(b['time']); dt=(t1-t0).total_seconds()
        if t0<time<t1:
            pa=[a['longitude'],a['latitude']]; pb=[b['longitude'],b['latitude']]
            if dt>1800 or distance(pa,pb)/dt>25 or abs(pa[0]-pb[0])>180: return None
            f=(time-t0).total_seconds()/dt
            return [pa[0]+f*(pb[0]-pa[0]),pa[1]+f*(pb[1]-pa[1])]
    return None

def geo_config(p):
    b=p.get('bounds')
    if not b: return None
    if not isinstance(b,dict): raise ValueError('Bounds must be an object.')
    b={k:num(b.get(k),k,-85 if k in ('south','north') else -180,85 if k in ('south','north') else 180) for k in ['west','east','south','north']}
    if not b['west']<b['east'] or not b['south']<b['north'] or b['east']-b['west']>5 or b['north']-b['south']>5: raise ValueError('Use ordered bounds covering no more than 5 degrees; antimeridian scenes are unsupported.')
    env={k:num(p.get(k,d),k,lo,hi) for k,d,lo,hi in [('current_east',0,-3,3),('current_north',0,-3,3),('wind_east',0,-50,50),('wind_north',0,-50,50),('windage',.03,0,.1),('uncertainty',.15,.01,2),('age_min',1,.25,48),('age_max',4,.25,48)]}
    if env['age_min']>env['age_max']: raise ValueError('Minimum age must not exceed maximum age.')
    return b,env

def analyze(p,asset_dir):
    if not isinstance(p,dict): raise ValueError('JSON body must be an object.')
    name=str(p.get('name','')).strip()
    if not name or len(name)>120: raise ValueError('Name is required and must be at most 120 characters.')
    observation=stamp(p.get('observation')); config=geo_config(p); tracks=parse_ais(p.get('ais_csv',''))
    image=decode_image(p.get('image_base64')); mode=p.get('model','trained')
    im,mask=segment(image,mode)
    asset_dir.mkdir(parents=True,exist_ok=True)
    im.save(asset_dir/'image.png'); Image.fromarray((mask*255).astype('uint8')).save(asset_dir/'mask.png')
    overlay=np.array(im); overlay[mask]=(overlay[mask]*.45+np.array([22,210,181])*.55).astype('uint8'); Image.fromarray(overlay).save(asset_dir/'overlay.png')
    labels,count=ndi.label(mask); regions=[]
    for i in range(1,count+1):
        ys,xs=np.where(labels==i)
        if len(xs)>=12: regions.append({'pixels':int(len(xs)),'x':float(xs.mean()),'y':float(ys.mean())})
    regions=sorted(regions,key=lambda r:r['pixels'],reverse=True)[:20]
    sources=[]; candidates=[]; geo={'type':'FeatureCollection','features':[]}
    if config:
        b,e=config; vx=e['current_east']+e['windage']*e['wind_east']; vy=e['current_north']+e['windage']*e['wind_north']
        for ri,r in enumerate(regions):
            lat=b['north']-(r['y']+.5)/WORK_SIZE[1]*(b['north']-b['south']); lon=b['west']+(r['x']+.5)/WORK_SIZE[0]*(b['east']-b['west'])
            r['longitude'],r['latitude']=lon,lat
            scale=111320*math.cos(math.radians(lat))
            if abs(scale)<1000: continue
            for age in np.linspace(e['age_min'],e['age_max'],9):
                seconds=float(age)*3600; center=[lon-vx*seconds/scale,lat-vy*seconds/111320]
                # Deterministic assumption radius; NOT a probability/confidence interval.
                radius=250+e['uncertainty']*seconds
                if not -180<=center[0]<=180 or not -85<=center[1]<=85: continue
                ring=[[center[0]+radius/scale*math.cos(a),center[1]+radius/111320*math.sin(a)] for a in np.linspace(0,2*math.pi,49)]
                ring[-1]=ring[0]
                s={'region':ri+1,'age_hours':float(age),'time':(observation-timedelta(seconds=seconds)).isoformat(),'center':center,'radius_m':radius}; sources.append(s)
                geo['features'].append({'type':'Feature','properties':s,'geometry':{'type':'Polygon','coordinates':[ring]}})
        for m,track in tracks.items():
            matches=[]
            for s in sources:
                pos=interpolate(track,stamp(s['time']))
                if pos:
                    d=distance(pos,s['center']); spatial=math.exp(-.5*(d/s['radius_m'])**2)
                    matches.append((spatial,d,s,pos))
            if not matches: continue
            spatial,d,s,pos=max(matches,key=lambda t:t[0]); coverage=len(matches)/len(sources)
            if spatial<.1: continue
            complete=1. if len(track)>1 else .5
            candidates.append({'mmsi':m,'name':track[0]['name'],'score':round(100*(.7*spatial+.2*coverage+.1*complete),2),'spatial_score':round(spatial,4),'temporal_coverage':round(coverage,4),'record_completeness':complete,'distance_m':round(d,1),'match_time':s['time'],'region':s['region'],'position':pos})
        candidates.sort(key=lambda c:c['score'],reverse=True)
    for m,track in tracks.items():
        coords=[[r['longitude'],r['latitude']] for r in track]
        geo['features'].append({'type':'Feature','properties':{'mmsi':m,'kind':'AIS track'},'geometry':{'type':'LineString','coordinates':coords} if len(coords)>1 else {'type':'Point','coordinates':coords[0]}})
    return {'name':name,'observation':observation.isoformat(),'notes':str(p.get('notes',''))[:4000],'model':mode,'image_size':list(image.size),'working_size':list(WORK_SIZE),'mask_fraction':round(float(mask.mean()),6),'regions':regions,'sources':sources,'candidates':candidates,'tracks':tracks,'bounds':config[0] if config else None,'environment':config[1] if config else None,'geojson':geo,'timeline':[{'time':observation.isoformat(),'event':'Image observation supplied by analyst'}]+[{'time':c['match_time'],'event':'Candidate association '+c['mmsi']} for c in candidates], 'warning':'Screening result only. Slick labels include seepage. Candidate scores are heuristic associations, not probabilities or proof of responsibility.'}
