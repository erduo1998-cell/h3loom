---
name: h3-video-runtime
description: 编译获批 H3 故事板脚本并在 AutoDL 生成、恢复和下载视频；用于阶段三执行与交付。
---

# MiniMax H3 执行

只执行冻结的故事板、语义锚点与 H3 脚本，不重新设计场景或写创意 prompt。默认交付独立 4K 候选、输出 SHA、delivery manifest 与关机/交棒收据，人工审片状态为 `human_review_pending`。

## 按当前状态推进

读取指定任务的 `task.json`，用 `broll-video next <task-id>` 定位状态；首次编译读取已批准 manifest，恢复只读取相关 attempt、provider、结果和计划。原始 SRT 与完整阶段一材料由编译器按需验证，不要求 Agent 每次重读。

范围、抽数与预算遵循[任务与授权契约](../../../docs/three-stage-workflow.md#任务与授权契约)。使用当前阶段批准字节，不能依据缺失结果、审美判断或旧文件新建付费尝试。

- 首次编译/计划：读[API 与生产绑定](references/api-contract.md)，执行 `compile-h3`、`plan-batch`。它们验证批准哈希、锚点、请求、预算及收据；通过后不再人工逐项重做相同检查。
- 恢复、失败、缺下载、换机或交棒：读[执行与恢复](references/execution-recovery.md)的相关部分，复用已有结果或 `prompt_id`。
- 凭据/实例改变：使用当次 SSH 命令和密码执行 `install-credentials`；秘密经安全本地输入，不写聊天、argv、环境或日志。
- 安装或栈变化时才运行 `verify-stack`；日常执行不反复核对整栈、重构或开关机。跨云迁移另见 [迁移契约](../../../docs/h3-stack-portability.md)。

编译和预算规划尽量在开机前完成；已运行实例不为本地计划反复开关机。标准入口：

```bash
broll-video compile-h3 <task-id>
broll-autodl plan-batch <task-id>
broll-autodl run-batch <task-id>
```

`run-batch` 使用冻结 `live-run.json`，不临场重估或重写请求。运行状态和成功收据足以判断下一步时，不重复 dry-run、导出 prompt 或搜索官方文档。

## 提交边界

- 唯一编译器为 `broll-video compile-h3`：固定 `precision_keyframes` / H3Keyframes / FL2V 8-step、4K、确定性 seed；每条连续 4–15 秒，3–5 个语义时间锚点。不手改 request、换 fast/Ref2V、加图或用临时脚本绕过编译器。
- 上传前代码门禁检查脚本与批准结构一致、口播原文字段泄漏及声音契约。时间码、动作、运镜、切点、转场和过渡均可保留，不额外设视觉白名单。失败时修复受影响的上游产物并按需重新批准，不绕过门禁。
- 最终 FL2VA 使用 `integrated_multimodal_description / overall_soundscape / non_diegetic_music`，`non_diegetic_music: N/A`，只含同步环境声和可见动作音效。H3 维持批准 AI 图片中的文字，不补写或换后期文字路线。
- 单生成线与单下载/校验/收据线有界并行，待下载队列上限 4；保留实例 lease、原子 reservation 和 `prompt_id`，不同时提交多个 GPU 请求，不等全部生成完再下载。
- 下载明确失败后，当前 GPU 任务收口并暂停新提交；`/prompt` 响应不确定且无 ID 时保留 reservation、停止重提。已有 ID 只恢复原任务。

## 完成与停止

文件快速收货只证明存在、可解码及基本媒体尺寸，不证明审美、文字或音轨正确。`sfx_only` 是提示词约束，当前无独立节点能硬禁 BGM 并保留音效；人工发现人声/音乐时停止新的付费尝试并审计批准输入，不擅自静音或后期补音。

两条流水线与 delivery 完成后，按任务级策略执行一次关机并验证 SSH 不可达，或保存用户明确授权的接力收据；异常保留实例供恢复，并报告仍可能计费。素材放在 `outputs/generated/<task-id>/` 与 `outputs/final/<task-id>/`，原始下载不被覆盖。交付后由用户审片并决定 `accept`，不增加默认深度 QC 矩阵。

只有用户要求持续监控才建立只读监控；按用户频率报告，未指定频率时仅通知有意义的变化、完成、失败或待用户行动。监控不授权重投、改参数或关机。
