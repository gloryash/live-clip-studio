from pathlib import Path
import json, itertools, collections

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / 'data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript'
O = D.parent / 'speaker-experiments/3dspeaker'
seg = json.loads((D/'segments.json').read_text())['segments']
man = json.loads((D/'manual-speaker-labels.json').read_text())['annotations']
deleted = set(json.loads((D/'deleted-turns.json').read_text()).get('ids', []))
diar = list(json.loads((O/'audio-16k-mono.json').read_text()).values())
def ov(s, d): return max(0.0, min(float(s['end']), float(d['stop'])) - max(float(s['start']), float(d['start'])))
pred = {}
for i, s in enumerate(seg, 1):
    hits = [(ov(s, d), int(d['speaker'])) for d in diar if ov(s, d) > 0]
    if hits: pred[i] = max(hits)[1]
    elif pred: pred[i] = pred[max(pred)]
pairs = [(man[str(i)], f'SPEAKER_{pred[i]:02d}') for i in pred if str(i) in man and i not in deleted]
gold = sorted(set(x for x, y in pairs)); actual = sorted(set(y for x, y in pairs)); best = (-1, None)
for vals in itertools.permutations(gold, len(actual)):
    mapping = dict(zip(actual, vals)); n = sum(mapping[y] == x for x, y in pairs)
    if n > best[0]: best = (n, mapping)
mapped = [(x, best[1][y]) for x, y in pairs]; cm = collections.Counter(mapped); stats = {}
for g in gold:
    tp = cm[g, g]; fp = sum(v for (x, y), v in cm.items() if y == g and x != g); fn = sum(v for (x, y), v in cm.items() if x == g and y != g)
    stats[g] = {'precision': tp/(tp+fp) if tp+fp else 0, 'recall': tp/(tp+fn) if tp+fn else 0, 'f1': 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0, 'support': sum(v for (x, y), v in cm.items() if x == g)}
out = {'model': 'modelscope/3D-Speaker CAM++ + FSMN-VAD + spectral clustering', 'evaluated': len(pairs), 'predicted': len(pred), 'accuracy': best[0]/len(pairs), 'macro_f1': sum(x['f1'] for x in stats.values())/len(stats), 'mapping_pred_to_gold': best[1], 'per_speaker': stats, 'confusion': {f'{x}->{y}': v for (x, y), v in cm.items()}}
(O/'metrics.json').write_text(json.dumps(out, ensure_ascii=False, indent=2)); print(json.dumps(out, ensure_ascii=False, indent=2))
