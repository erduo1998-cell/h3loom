---
name: broll-storyboard-producer
description: 将获批 H3 镜头计划生成四格故事板、语义锚点和冻结脚本；用于阶段二样板、全量生成或修订。
---

# B-roll 四格故事板

输入为用户共同批准的 `visual-lock.json/md`、`shot-plan.json/md` 及任务账本；输出为获批四格板、干净锚点和含 H3 脚本的 `storyboard-manifest.json`。仅在实际生图时加载 `imagegen` 并使用内置 Codex Imagine。本阶段不重新拆 SRT、暗换风格或执行 GPU。

## 计划与生成

1. 定位当前 `task.json`，确认 `shot_plan_approval` 来自 `explicit_user_instruction`，且阶段一文件、审阅包和账本 SHA-256 仍匹配。沿用两类参考、场景与摄影，范围服从[任务与授权契约](../../../docs/three-stage-workflow.md#任务与授权契约)。需要改变冻结设计时回阶段一修订并重新批准。
2. 编写 `storyboard-board-plan.json` 时读[四格与 Manifest 契约](references/four-panel-contract.md)。先按语义确定每个 4–15 秒单元需 1–4 张板，记录各板时间、信息范围和板数理由；四格足够就用一张，不按时长套公式。
3. 每次 Imagine 调用生成一张 2×2 四格板。逐格明确相对时间、镜头与信息推进；新增板承接上一板末格状态，不重置主体或故事。同镜头可连续，真正切镜须增加信息并改变景别、角度或视点。
4. 沿用 `text_strategy`：单一主体、动作与主文字焦点，文字正面、巨大、高对比并稳定停留。精确文字逐字写入 prompt 并检查结果；乱码或错字留在图片阶段单点修订，不带入 H3，也不改用截图、录屏、可控 UI 或后期叠字。修订仍受当前生成授权范围约束；持续失败时带具体样板提出可执行简化方案，不无限重抽。

## 样板与全量

先生成 1–2 个能暴露风格、摄影或复杂节拍问题的代表单元，写入 `storyboard-sample.json`。同构系列的所有必需成员与拟议画面须已在阶段一公开，样板通过只证明模板可行。收到用户明确批准后由 Agent 执行：

```bash
broll-video approve-storyboard-sample <task-id> --approval-source explicit_user_instruction
```

随后生成全量，样板原字节进入 manifest。保留原始板 `storyboards/raw/`、审阅板 `review/`、Imagine 提示词 `prompts/` 与干净图 `generation/`。从每单元的全部 Panel 选择 3–5 张差异明显的锚点，按语义时间记录 `generation_anchor_times_seconds`；整期不超过 `ceil(4.1 × 镜头数)`。生成图无边框、箭头、时间码和底栏。

## 冻结脚本并交付

全量确认前执行：

```bash
broll-video prepare-h3-prompts <task-id>
```

它从实际 Panel 确定性生成最长 1600 字符的 `h3_request_prompt` 并写入 `schema_version: 3.0` 的 manifest，与图片、锚点时间和 `h3_visual_guard` 一起冻结。图片是主体、空间、构图、材质、光色及画内文字的唯一权威；脚本补充时间、动作、运镜、切点、物理过渡与同步音效，不写入 `source_quote / spoken_addition / 口播逐字稿`，不让 H3 补写文字。声音固定 `sfx_only`，禁止人声、旁白、对话、歌唱、音乐和画外声。

修复缺图、错字、Panel/锚点错位或脚本缺失后，交付全量分镜供用户确认。用户无需逐字审查模板脚本，代码负责一致性门禁。收到明确批准后由 Agent 执行：

```bash
broll-video approve-storyboards <task-id> --approval-source explicit_user_instruction
```

批准冻结 manifest、原始板、审阅板、Imagine prompt、锚点与脚本的 SHA-256；任何相关字节或结构变化须重新批准。未批准停在本阶段；批准有效且执行已授权时转入 `h3-video-runtime`，不另加确认。
