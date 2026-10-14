from pathlib import Path
import json, itertools, collections, sys
import numpy as np, torch
ROOT=Path(__file__).resolve().parents[1]; D=ROOT/'data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript'; O=D.parent/'speaker-experiments'; sys.path.insert(0,'/tmp/3D-Speaker')
from modelscope.hub.snapshot_download import snapshot_download
from speakerlab.process.processor import FBank
from speakerlab.models.eres2net.ERes2NetV2 import ERes2NetV2
seg=json.loads((D/'segments.json').read_text())['segments']; man=json.loads((D/'manual-speaker-labels.json').read_text())['annotations']; deleted=set(json.loads((D/'deleted-turns.json').read_text()).get('ids',[])); from live_clip_studio.diarization import load_audio
audio,sr=load_audio(D/'audio-16k-mono.wav'); cache=snapshot_download('iic/speech_eres2netv2_sv_zh-cn_16k-common',revision='v1.0.1'); ck=Path(cache)/'pretrained_eres2netv2.ckpt'; model=ERes2NetV2(feat_dim=80,embedding_size=192,baseWidth=26,scale=2,expansion=2); model.load_state_dict(torch.load(ck,map_location='cpu')); model.eval(); fe=FBank(80,sample_rate=16000,mean_nor=True); em=[];ids=[]
for i,s in enumerate(seg):
 a,b=float(s['start']),float(s['end']);
 if b-a<1:continue
 x=audio[int(a*sr):int(b*sr)];
 if len(x)<sr:continue
 with torch.no_grad(): v=model(fe(torch.tensor(x).unsqueeze(0)).unsqueeze(0)).squeeze().numpy()
 em.append(v/(np.linalg.norm(v)+1e-9));ids.append(i)
em=np.asarray(em);np.savez_compressed(O/'eres2netv2-embeddings.npz',embeddings=em,indices=ids)
from sklearn.cluster import AgglomerativeClustering
for k in (4,):
 labels=AgglomerativeClustering(n_clusters=k,metric='cosine',linkage='average').fit_predict(em); pred={i+1:int(x) for i,x in zip(ids,labels)}; pairs=[(man[str(i)],pred[i]) for i in pred if str(i) in man and i not in deleted]; A=sorted(set(x for x,y in pairs));B=sorted(set(y for x,y in pairs));best=max(((sum(dict(zip(B,v))[y]==x for x,y in pairs),dict(zip(B,v))) for v in itertools.permutations(A,len(B))),key=lambda x:x[0]); print(json.dumps({'model':'3D-Speaker ERes2NetV2','evaluated':len(pairs),'accuracy':best[0]/len(pairs),'mapping':best[1]},ensure_ascii=False))
