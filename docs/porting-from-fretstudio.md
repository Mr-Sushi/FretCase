# 从 FretStudio 移植

FretCase 只用 FretStudio 的一部分。移植时以 FretStudio 本地工作区的最新文件为准，不要从它的 `main` 提交拉：2026 年 11 月的几轮修复（指法库错标、调号解析、和弦拼写、变调夹编配等）在写这份文档时还没有提交。

移植的原则：

- 和声、编配、可弹性这些已经过测试和专家基准校准的部分，原样搬进 `engine/`，连同它们的测试。
- 和 ABC 字符串、学习者档案、练习流程绑在一起的部分不搬，按新的歌曲模型重写。
- 搬过来的代码不顺手重构；要改结构，先在 `docs/` 里写明再改。

## 搬进 `engine/`

| FretStudio 文件 | 用途 | 备注 |
| --- | --- | --- |
| `server/harmony_reasoning.py` | HRE 打分 | 运行时读 `hre_calibration.json` |
| `server/arrangement_solver.py` | ACS 指法求解 | |
| `server/capo.py` | 变调夹编配 | |
| `server/chord_spelling.py` | 按调拼写和弦 | |
| `server/chord_changes.py` | 换和弦度量 | |
| `server/voicing_check.py` | 指法校验 | |
| `server/constraint_engine.py` | H1–H4 约束 | 已支持 4/4、3/4、6/8、2/4 |
| `server/candidate_sources.py` | 进行库、规则、混合候选 | 离线模式的基础 |
| `server/candidate_summary.py` | 候选摘要 | 只取打分部分，学习者相关字段去掉 |
| `server/offline_melody.py` | 离线旋律 | 无模型时的兜底 |
| `server/data/guitar_voicings.json` | 指法库（242 符号 / 1,051 指法） | 来自 MIT 许可的 chords-db，保留出处 |
| `server/data/hre_calibration.json`、`hre_priors.json` | HRE 权重与先验 | |
| `server/data/progression_library.json` | 和弦进行库 | |
| `server/data/acs_type_difficulty.json`、`acs_transition_priors.json`、`beginner_shapes.json` | ACS 数据 | |
| 对应的 `server/test_*.py` | 测试 | 搬过来后必须全部通过 |

## 改写后搬进 `server/`

| FretStudio 文件 | 处理 |
| --- | --- |
| `server/music_representation.py` | 只保留 ABC 解析与写出，作为导入导出；内部表示改用 JSON 歌曲模型 |
| `server/musicxml_export.py` | 改为从歌曲模型导出，支持六轨 |
| `server/version_tree.py` | 参考它的思路写操作历史（撤销、换一个） |
| `server/study_log.py` | 原样可用，事件类型改为 FretCase 的 |
| `server/audio_to_midi_worker.py`、`audio_seed.py` | 参考，哼唱转谱改用 Basic Pitch |

## 前端参考

| FretStudio 文件 | 处理 |
| --- | --- |
| `client/src/lib/rhythmDifficulty.ts`、`rhythmPresets.ts`、`rhythmRealization.ts` | 搬过来，对应"疏密"旋钮 |
| `client/src/lib/capo.ts`、`startKeys.ts`、`numberedDegrees.ts` | 搬过来 |
| `client/src/lib/usePlayback.ts` | 只作参考，播放改用 Tone.js |

## 不移植

学习者档案（`learner_model.py`、`learner_store.py`）、练习计划与晋级（`practice_support.py`）、专家评测（`expert_eval.py`、`expert_runtime.py`）、`recourse_engine.py`、`harmony_reranker.py`、论文与评测脚本、FretStudio 的五步界面。
