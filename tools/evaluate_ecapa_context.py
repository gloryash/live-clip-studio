from pathlib import Path
import json, itertools, collections
import numpy as np
import torch
from speechbrain.inference.classifiers import EncoderClassifier
from live_clip_studio.diarization import load_audio
spec=Path(__file__).resolve().parents[1]; D=spec/'data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript'; O=D.parent/'speaker-experiments'
seg=json.loads((D/'segments.json').read_text())['segments']; man=json.loads((D/'manual-speaker-labels.json').read_text())['annotations']; deleted=set(json.loads((D/'deleted-turns.json').read_text()).get('ids',[])); audio,sr=load_audio(D/'audio-16k-mono.wav'); clf=EncoderClassifier.from_hparams(source='speechbrain/spkrec-ecapa-voxceleb',savedir=str(Path.home()/'.cache/live-clip-studio/speechbrain-spkrec-ecapa'),run_opts={'device':'cpu'})
emb=[]
for i,s in enumerate(seg):
    a,b=float(s['start']),float(s['end']); dur=b-a; center=(a+b)/2; left=max(0,center-max(0.5,dur/2)); right=min(len(audio)/sr,center+max(0.5,dur/2)); x=audio[int(left*sr):int(right*sr)]
    if len(x)<sr: x=np.pad(x,(0,sr-len(x)))
    with torch.no_grad(): v=clf.encode_batch(torch.tensor(x,dtype=torch.float32).unsqueeze(0)).squeeze().cpu().numpy()
    v=v/(np.linalg.norm(v)+1e-9); emb.append(v)
emb=np.asarray(emb); np.savez_compressed(O/'ecapa-context-embeddings.npz',embeddings=emb)
from sklearn.cluster import AgglomerativeClustering
def smooth(labels):
    # context-aware local majority, independent of speaker identity
    out=labels.copy()
    for i in range(1,len(labels)-1):
        if labels[i-1]==labels[i+1] and labels[i]!=labels[i-1]: out[i]=labels[i-1]
    return out
for k in (4,):
    labels=np.zeros(len(emb),dtype=int); sums={}; starts=[float(x['start']) for x in seg]; w=600; ws=(min(starts)//w)*w
    while ws<=max(starts):
        ids=[i for i,x in enumerate(seg) if ws<=float(x['start'])<ws+w]; ws+=w
        if not ids: continue
        ll=AgglomerativeClustering(n_clusters=min(k,len(ids)),metric='cosine',linkage='average').fit_predict(emb[ids]); local=list(sorted(set(ll),key=lambda q:list(ll).index(q))); mapping={}
        for q in local:
            vec=emb[[ids[j] for j,v in enumerate(ll) if v==q]].mean(0); vec/=np.linalg.norm(vec)+1e-9
            if sums: mapping[q]=max(sums,key=lambda z:float(vec@((sums[z]/(np.linalg.norm(sums[z])+1e-9)))))
            else: mapping[q]=q
        for q in local:
            target=mapping[q]; members=[ids[j] for j,v in enumerate(ll) if v==q]; labels[members]=target; sums[target]=sums.get(target,0)+emb[members].sum(0)
    labels=smooth(labels); gold=sorted(set(man.values())); actual=sorted(set(labels.tolist())); best=(-1,None)
    for vals in itertools.permutations(gold,len(actual)):
        m=dict(zip(actual,vals)); n=sum(m[int(labels[i-1])]==man[str(i)] for i in range(1,len(seg)+1) if str(i) in man and i not in deleted)
        if n>best[0]:best=(n,m)
    pairs=[(man[str(i)],best[1][int(labels[i-1])]) for i in range(1,len(seg)+1) if str(i) in man and i not in deleted]; cm=collections.Counter(pairs); stats={}
    for g in gold:
        tp=cm[g,g];fp=sum(v for (x,y),v in cm.items() if y==g and x!=g);fn=sum(v for (x,y),v in cm.items() if x==g and y!=g);stats[g]={'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0}
    out={'model':'SpeechBrain ECAPA + 1s context + 600s window','evaluated':len(pairs),'accuracy':best[0]/len(pairs),'macro_f1':sum(x['f1'] for x in stats.values())/len(stats),'mapping':best[1],'per_speaker':stats};(O/'ecapa-context.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False,indent=2))
