from pathlib import Path
import json,itertools,collections
import numpy as np
from live_clip_studio.diarization import cluster_embeddings,canonicalize
ROOT=Path(__file__).resolve().parents[1]; D=ROOT/'data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript'; O=D.parent/'speaker-experiments'
seg=json.loads((D/'segments.json').read_text())['segments']; man=json.loads((D/'manual-speaker-labels.json').read_text())['annotations']; deleted=set(json.loads((D/'deleted-turns.json').read_text()).get('ids',[])); z=np.load(O/'ecapa-embeddings.npz'); emb=z['embeddings']; idx=z['indices']
for k in (2,3,4):
 pred={int(i)+1:s for i,s in zip(idx,canonicalize(cluster_embeddings(emb,k)))}; pairs=[(man[str(i)],pred[i]) for i in pred if str(i) in man and i not in deleted]; gold=sorted(set(x for x,y in pairs)); actual=sorted(set(y for x,y in pairs));
 best=(-1,None)
 # bijection if equal; otherwise report best assignment with dummy labels
 if len(actual)==len(gold):
  for vals in itertools.permutations(actual):
   m=dict(zip(actual,vals)); n=sum(m[y]==x for x,y in pairs)
   if n>best[0]:best=(n,m)
 else:
  for vals in itertools.product(gold,repeat=len(actual)):
   m=dict(zip(actual,vals)); n=sum(m[y]==x for x,y in pairs)
   if n>best[0]:best=(n,m)
 mapped=[(x,best[1][y]) for x,y in pairs]; cm=collections.Counter(mapped); stats={}
 for g in gold:
  tp=cm[g,g]; fp=sum(v for (x,y),v in cm.items() if y==g and x!=g); fn=sum(v for (x,y),v in cm.items() if x==g and y!=g); stats[g]={'precision':tp/(tp+fp) if tp+fp else 0,'recall':tp/(tp+fn) if tp+fn else 0,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,'support':sum(v for (x,y),v in cm.items() if x==g)}
 macro=sum(s['f1'] for s in stats.values())/len(stats); out={'model':'speechbrain/spkrec-ecapa-voxceleb','clusters':k,'evaluated':len(pairs),'accuracy':best[0]/len(pairs),'macro_f1':macro,'mapping_pred_to_gold':best[1],'per_speaker':stats,'confusion':{f'{x}->{y}':v for (x,y),v in cm.items()}}
 (O/f'score-{k}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False))
