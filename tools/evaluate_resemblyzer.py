from pathlib import Path
import json,itertools,collections
import numpy as np
from resemblyzer import VoiceEncoder
from live_clip_studio.diarization import load_audio,cluster_embeddings,canonicalize
ROOT=Path(__file__).resolve().parents[1]; D=ROOT/'data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript'; O=D.parent/'speaker-experiments'; seg=json.loads((D/'segments.json').read_text())['segments']; man=json.loads((D/'manual-speaker-labels.json').read_text())['annotations']; deleted=set(json.loads((D/'deleted-turns.json').read_text()).get('ids',[])); audio,sr=load_audio(D/'audio-16k-mono.wav'); enc=VoiceEncoder('cpu'); em=[]; idx=[]
for i,s in enumerate(seg):
 if float(s['end'])-float(s['start'])<1: continue
 x=audio[int(s['start']*sr):int(s['end']*sr)]
 if len(x)<sr: continue
 em.append(enc.embed_utterance(x)); idx.append(i)
em=np.asarray(em); np.savez_compressed(O/'resemblyzer-embeddings.npz',embeddings=em,indices=idx)
for k in (4,):
 pred={i+1:v for i,v in zip(idx,canonicalize(cluster_embeddings(em,k)))}; pairs=[(man[str(i)],pred[i]) for i in pred if str(i) in man and i not in deleted]; gold=sorted(set(x for x,y in pairs)); actual=sorted(set(y for x,y in pairs)); best=(-1,None)
 for vals in itertools.permutations(gold,len(actual)):
  mm=dict(zip(actual,vals)); n=sum(mm[y]==x for x,y in pairs)
  if n>best[0]:best=(n,mm)
 mapped=[(x,best[1][y]) for x,y in pairs]; cm=collections.Counter(mapped); stats={}
 for g in gold:
  tp=cm[g,g];fp=sum(v for (x,y),v in cm.items() if y==g and x!=g);fn=sum(v for (x,y),v in cm.items() if x==g and y!=g);stats[g]={'precision':tp/(tp+fp) if tp+fp else 0,'recall':tp/(tp+fn) if tp+fn else 0,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,'support':sum(v for (x,y),v in cm.items() if x==g)}
 out={'model':'resemblyzer/VoiceEncoder','clusters':k,'evaluated':len(pairs),'accuracy':best[0]/len(pairs),'macro_f1':sum(x['f1'] for x in stats.values())/len(stats),'mapping_pred_to_gold':best[1],'per_speaker':stats};(O/'resemblyzer.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False))
