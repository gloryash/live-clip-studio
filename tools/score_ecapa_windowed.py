from pathlib import Path
import json, itertools, collections, importlib.util
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / 'data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript'
O = D.parent / 'speaker-experiments'
spec = importlib.util.spec_from_file_location('legacy_diar', '/Users/panyupeng/.codex/skills/video-copy-extractor/scripts/diarize_speechbrain.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
seg = json.loads((D/'segments.json').read_text())['segments']
man = json.loads((D/'manual-speaker-labels.json').read_text())['annotations']
deleted = set(json.loads((D/'deleted-turns.json').read_text()).get('ids', []))
z = np.load(O/'ecapa-embeddings.npz'); emb=z['embeddings']; idx=z['indices']
rows=[{'index':int(i), 'start':seg[int(i)]['start'], 'end':seg[int(i)]['end'], 'text':seg[int(i)].get('text','')} for i in idx]
for w in (120,300,600):
    labels,_=m.windowed_cluster_labels(emb, rows, 4, w)
    pred={int(i)+1:f'SPEAKER_{int(s):02d}' for i,s in zip(idx,labels)}
    pairs=[(man[str(i)],pred[i]) for i in pred if str(i) in man and i not in deleted]
    gold=sorted(set(x for x,y in pairs)); actual=sorted(set(y for x,y in pairs)); best=(-1,None)
    for vals in itertools.permutations(gold, len(actual)):
        mm=dict(zip(actual,vals)); n=sum(mm[y]==x for x,y in pairs)
        if n>best[0]: best=(n,mm)
    mapped=[(x,best[1][y]) for x,y in pairs]; cm=collections.Counter(mapped); stats={}
    for g in gold:
        tp=cm[g,g]; fp=sum(v for (x,y),v in cm.items() if y==g and x!=g); fn=sum(v for (x,y),v in cm.items() if x==g and y!=g)
        stats[g]={'precision':tp/(tp+fp) if tp+fp else 0,'recall':tp/(tp+fn) if tp+fn else 0,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,'support':sum(v for (x,y),v in cm.items() if x==g)}
    out={'model':'speechbrain ECAPA + windowed clustering','window_seconds':w,'clusters':4,'evaluated':len(pairs),'accuracy':best[0]/len(pairs),'macro_f1':sum(x['f1'] for x in stats.values())/len(stats),'mapping_pred_to_gold':best[1],'per_speaker':stats,'confusion':{f'{x}->{y}':v for (x,y),v in cm.items()}}
    (O/f'ecapa-windowed-{w}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)); print(json.dumps(out,ensure_ascii=False))
