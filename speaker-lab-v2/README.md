# Speaker Lab V2

独立验证局部过聚类、动态说话人注册和跨尺度人数估计。该目录不会修改 Live Clip Studio 的生产说话人结果。

## 数据隔离

- `infer` 只读取 `segments.json` 和匿名 embedding `.npz`。
- `score` 在推理完成后单独读取人工标签。
- 当前视频是冻结测试集，评分结果不得用于修改本次运行参数后重跑。

## 运行

```bash
PYTHONPATH=src ../.venv/bin/python -m speaker_lab_v2.pipeline infer \
  --segments ../data/<job-id>/transcript/segments.json \
  --embedding ECAPA=../data/<job-id>/speaker-experiments/ecapa-embeddings.npz \
  --output outputs/run-id

PYTHONPATH=src ../.venv/bin/python -m speaker_lab_v2.scoring \
  --prediction outputs/run-id/inferred-speakers.json \
  --manual-labels ../data/<job-id>/transcript/manual-speaker-labels.json \
  --segments ../data/<job-id>/transcript/segments.json \
  --output outputs/run-id/metrics.json
```
