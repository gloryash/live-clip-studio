# 同人验证与注册语音实验设计

日期：2026-07-25

## 路线A：官方固定阈值AHC

- ECAPA使用SpeechBrain官方speaker verification默认余弦阈值`0.25`。
- CAM++与ERes2NetV2使用3D-Speaker `AHCluster`默认阈值`0.4`。
- 使用average-linkage AHC自动得到簇数，不提供人数和人工标签。
- 小于等于4条的极小簇按3D-Speaker默认逻辑并入最近主要簇。

该路线验证外部训练模型自带阈值能否直接迁移到当前中文直播领域。

## 路线B：注册语音分类

- 每位人工说话人按时间选择最早的`1/3/5`条、持续时间至少2秒的长语音作为注册样本。
- 注册样本从评估集中排除。
- 每位说话人的注册中心由注册embedding等权平均并归一化。
- 剩余有embedding的长字幕分配给余弦相似度最高的注册中心。
- 不调阈值、不挑选最好片段，固定按时间最早顺序。

该路线明确属于有监督speaker enrollment，不作为无监督人数识别成绩。它用于判断产品若增加少量注册语音，现有embedding是否足够。

## 防止误解

- 当前视频已经是开发集。
- 路线A与路线B必须分表报告。
- 注册实验不能被表述为自动发现说话人。
- 三个模型、三个注册数量全部预先运行，结果不用于修改当前参数后重跑。

## 输出

- `outputs/frozen-dev-v3/ahc-predictions.json`
- `outputs/frozen-dev-v3/ahc-metrics.json`
- `outputs/frozen-dev-v3/enrollment-metrics.json`
- 人数、总体指标、每人召回、注册样本ID、剩余评估数量和运行压力。
