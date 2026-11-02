"""Reproducible CPU baseline. Splits are by source image, never by pixels."""
import sys, json, csv, time, platform
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analysis import features, WORK_SIZE, ROOT
import numpy as np
from PIL import Image
from sklearn.ensemble import RandomForestClassifier
import sklearn, joblib
DATA=ROOT/'data/public'

def rows(split): return list(csv.DictReader((DATA/f'splits/{split}.csv').read_text(encoding='utf-8-sig').splitlines()))
def sample(row):
    image=Image.open(DATA/row['image_path']).convert('RGB').resize(WORK_SIZE,Image.Resampling.BILINEAR)
    mask=np.array(Image.open(DATA/row['mask_path']).resize(WORK_SIZE,Image.Resampling.NEAREST))>0
    if mask.ndim!=2: raise ValueError('Expected single-channel mask')
    return image,mask

def counts(y,p):
    return np.array([np.sum(y&p),np.sum(~y&p),np.sum(y&~p),np.sum(~y&~p)],dtype=np.int64)
def metrics(c):
    tp,fp,fn,tn=map(int,c)
    def div(a,b): return a/b if b else 0.
    return {'iou':div(tp,tp+fp+fn),'precision':div(tp,tp+fp),'recall':div(tp,tp+fn),'f1':div(2*tp,2*tp+fp+fn),'pixel_accuracy':div(tp+tn,tp+fp+fn+tn),'tp':tp,'fp':fp,'fn':fn,'tn':tn}

def main():
    started=time.perf_counter(); rng=np.random.default_rng(42)
    splits={s:rows(s) for s in ['train','val','test']}
    groups={s:{r['sample_id'].split('_TILE')[0] for r in rs} for s,rs in splits.items()}
    assert not(groups['train']&groups['val'] or groups['train']&groups['test'] or groups['val']&groups['test']), 'Source acquisition leakage'
    X=[];Y=[]
    for r in splits['train']:
        im,y=sample(r); f=features(im); y=y.ravel(); indices=[]
        for val in [False,True]:
            ids=np.flatnonzero(y==val)
            if len(ids): indices.extend(rng.choice(ids,min(500,len(ids)),replace=False))
        X.append(f[indices]);Y.append(y[indices])
    model=RandomForestClassifier(n_estimators=48,max_depth=14,min_samples_leaf=8,n_jobs=2,random_state=42)
    model.fit(np.concatenate(X),np.concatenate(Y)); print('Training complete',flush=True)
    thresholds=np.arange(.2,.81,.05); conf=np.zeros((len(thresholds),4),dtype=np.int64)
    for r in splits['val']:
        im,y=sample(r); prob=model.predict_proba(features(im))[:,1].reshape(y.shape)
        for j,t in enumerate(thresholds): conf[j]+=counts(y,prob>=t)
    best=int(np.argmax([metrics(c)['iou'] for c in conf])); threshold=float(thresholds[best])
    ROOT.joinpath('models').mkdir(exist_ok=True)
    joblib.dump({'estimator':model,'threshold':threshold,'working_size':WORK_SIZE,'sklearn_version':sklearn.__version__},ROOT/'models/segmenter.joblib',compress=3)
    total=np.zeros(4,dtype=np.int64); baseline=np.zeros(4,dtype=np.int64); detail=[]; lat=[]
    for r in splits['test']:
        im,y=sample(r); start=time.perf_counter(); p=model.predict_proba(features(im))[:,1].reshape(y.shape)>=threshold; lat.append(time.perf_counter()-start)
        c=counts(y,p);total+=c
        g=np.array(im.convert('L'));baseline+=counts(y,g<np.percentile(g,18))
        detail.append({'sample_id':r['sample_id'],**metrics(c)})
    report={'dataset':'Garcia-INPE oilspill-detection-dataset','commit':'1b9a62c30a9da9698eb470562aa976f9bd1e8fc3','split_counts':{s:len(rs) for s,rs in splits.items()},'source_groups':{s:sorted(v) for s,v in groups.items()},'resolution':list(WORK_SIZE),'train_pixels_sampled':sum(len(y) for y in Y),'seed':42,'threshold':threshold,'validation':metrics(conf[best]),'test':metrics(total),'dark_baseline_test':metrics(baseline),'test_inference_seconds_median':float(np.median(lat)),'elapsed_seconds':time.perf_counter()-started,'python':platform.python_version(),'sklearn':sklearn.__version__,'scope':'Binary slick versus background at 200x150. Includes seepage. No attribution ground truth. No comparison with full-resolution published metrics.'}
    (ROOT/'reports/metrics.json').write_text(json.dumps(report,indent=2))
    with (ROOT/'reports/test_per_image.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=detail[0].keys()); w.writeheader();w.writerows(detail)
    print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':main()
