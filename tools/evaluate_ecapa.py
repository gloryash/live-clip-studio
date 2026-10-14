from pathlib import Path
import json, itertools, collections, sys
import numpy as np
from live_clip_studio.diarization import load_audio, encode_segments, cluster_embeddings, canonicalize
from speechbrain.inference.classifiers import EncoderClassifier

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript'
OUT=DATA.parent/'speaker-experiments'; OUT.mkdir(exist_ok=True)
segments=json.loads((DATA/'segments.json').read_text())['segments']
manual=json.loads((DATA/'manual-speaker-labels.json').read_text())['annotations']
deleted=set(json.loads((DATA/'deleted-turns.json').read_text()).get('ids',[]))
audio,sr=load_audio(DATA/'audio-16k-mono.wav')
classifier=EncoderClassifier.from_hparams(source='speechbrain/spkrec-ecapa-voxceleb',savedir=str(Path.home()/'.cache/live-clip-studio/speechbrain-spkrec-ecapa'),run_opts={'device':'cpu'})
emb,rows=encode_segments(classifier,audio,sr,segments)
np.savez_compressed(OUT/'ecapa-embeddings.npz',embeddings=emb,indices=np.array([r['index'] for r in rows]))
for k in (2,3,4):
 labels=canonicalize(cluster_embeddings(emb,k)); pred={str(r['index']+1):s for r,s in zip(rows,labels)}
 pairs=[(manual[str(i)],pred[str(i)]) for i in range(1,len(segments)+1) if str(i) in manual and str(i) in pred and i not in deleted]
 A=sorted(set(x for x,y in pairs)); B=sorted(set(y for x,y in pairs)); best=(0,None)
 for vals in itertools.product(B,repeat=len(A)):
  m=dict(zip(A,vals)); n=sum(m[x]==y for x,y in pairs)
  if n>best[0]: best=(n,m)
 conf=collections.Counter((x,best[1][x],y) for x,y in pairs)
 result={'model':'speechbrain/spkrec-ecapa-voxceleb','clusters':k,'usable_segments':len(rows),'evaluated':len(pairs),'accuracy':best[0]/len(pairs),'mapping':best[1],'confusion':{f'{x}->{y}':n for (x,_,y),n in conf.items()}}
 (OUT/f'ecapa-global-{k}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps(result,ensure_ascii=False))
