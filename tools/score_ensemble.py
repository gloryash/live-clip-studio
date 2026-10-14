from pathlib import Path
import json, itertools, collections, importlib.util
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript'; O=D.parent/'speaker-experiments'
sp=importlib.util.spec_from_file_location('legacy','/Users/panyupeng/.codex/skills/video-copy-extractor/scripts/diarize_speechbrain.py'); legacy=importlib.util.module_from_spec(sp); sp.loader.exec_module(legacy)
seg=json.loads((D/'segments.json').read_text())['segments']; man=json.loads((D/'manual-speaker-labels.json').read_text())['annotations']; deleted=set(json.loads((D/'deleted-turns.json').read_text()).get('ids',[]))
z=np.load(O/'ecapa-embeddings.npz'); emb=z['embeddings']; idx=z['indices']; rows=[{'index':int(i),'start':seg[int(i)]['start'],'end':seg[int(i)]['end']} for i in idx]
ep={int(i)+1:int(x) for i,x in zip(idx,legacy.windowed_cluster_labels(emb,rows,4,600)[0])}
dj=list(json.loads((O/'3dspeaker/audio-16k-mono.json').read_text()).values())
def ov(s,d): return max(0,min(float(s['end']),float(d['stop']))-max(float(s['start']),float(d['start'])))
dp={}
for i,s in enumerate(seg,1):
    h=[(ov(s,d),int(d['speaker'])) for d in dj if ov(s,d)>0]
    if h: dp[i]=max(h)[1]
    elif dp: dp[i]=dp[max(dp)]
votes=collections.Counter((ep[i],dp[i]) for i in ep if i in dp); a=sorted(set(ep.values())); b=sorted(set(dp.values())); best=(-1,None)
for vals in itertools.permutations(a,len(b)):
    m=dict(zip(b,vals)); score=sum(v for (x,y),v in votes.items() if m[x]==y)
    if score>best[0]: best=(score,m)
pred={i:(ep[i] if i in ep else best[1].get(dp[i],0)) for i in range(1,len(seg)+1) if i in dp or i in ep}
gold=sorted(set(man.values())); actual=sorted(set(pred.values())); chosen=(-1,None)
for vals in itertools.permutations(gold,len(actual)):
    m=dict(zip(actual,vals)); n=sum(m[pred[i]]==man[str(i)] for i in pred if str(i) in man and i not in deleted)
    if n>chosen[0]: chosen=(n,m)
pairs=[(man[str(i)],chosen[1][pred[i]]) for i in pred if str(i) in man and i not in deleted]; cm=collections.Counter(pairs); stats={}
for g in gold:
    tp=cm[g,g]; fp=sum(v for (x,y),v in cm.items() if y==g and x!=g); fn=sum(v for (x,y),v in cm.items() if x==g and y!=g)
    stats[g]={'precision':tp/(tp+fp) if tp+fp else 0,'recall':tp/(tp+fn) if tp+fn else 0,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0}
out={'model':'ECAPA windowed 600s + 3D-Speaker unsupervised consensus','evaluated':len(pairs),'accuracy':chosen[0]/len(pairs),'macro_f1':sum(x['f1'] for x in stats.values())/len(stats),'per_speaker':stats,'unsupervised_alignment':best[1]}
(O/'ensemble.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)); print(json.dumps(out,ensure_ascii=False,indent=2))
