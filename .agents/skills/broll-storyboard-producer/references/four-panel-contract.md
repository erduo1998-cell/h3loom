# 四格与 Manifest 契约

编写 board plan、Imagine prompt 或 manifest 时查本文件；只修订已有板时读取受影响部分。格式以 [board plan schema](../../../../schemas/storyboard-board-plan.schema.json) 和 [manifest schema](../../../../schemas/storyboard-manifest.schema.json) 为准。

## 时间与层级

一个 4–15 秒 H3 单元先按语义规划 1–4 张板，每板严格 4 个 Panel，编号 1–4。板数取决于信息、动作与镜头容量，须在调用 Imagine 前写入 `storyboard-board-plan.json`；发现计划不可执行时先修订相关计划和必要审批，再生成。

`time / start_seconds / end_seconds` 均为当前单元内的相对时间。一个 beat 可由多个 Panel 表达起点、变化和结果，轻微信息也可合并；不可为了四格均分时间。跨板 Panel 1 延续上一板末格的主体、物理状态、视线、方向或动作。

Panel 记录以下信息：

```text
panel_number, time, start_seconds, end_seconds, spoken_addition
shot_number, framing, camera, shot_size, camera_angle, viewpoint, transition_in
visual_content, continuity_anchor, text_strategy, required_text[]
```

镜头编号按单元连续，不随新板归 1。只有单元开头使用 `Shot 1 + start`；同镜头继续用 `continue`，新镜头递增编号并用切换类 `transition_in`。变化应增加信息，允许同一 Shot 内多个连续状态，不强迫每格切镜。

## Imagine 提示词骨架

以下是首板示例；后续板使用实际编号和承接关系：

```text
Use case: illustration-story
Asset type: a cinematic 2x2 storyboard sheet for one continuous {duration}-second H3 video
Input images: Image 1 = content/style authority; Image 2 = talking-head palette, exposure, lighting and edit-rhythm reference

这是同一条 {duration} 秒 H3 视频的剪辑分镜故事板。
严格生成一张 2×2 故事板，恰好四个 Panel，按左上、右上、左下、右下阅读。
Panel 1 | Shot 1 | {time} | start：{framing}；{camera}；shot_size={shot_size}；camera_angle={camera_angle}；viewpoint={viewpoint}；{visual_content}
Panel 1 required_text: {必要文字原文的 JSON 数组，无则 []}
Panel 2–4：各自写出同一组字段，沿用计划中的镜头编号与 transition_in。
连续性：{主体、道具、空间、材质、光色、比例、画面方向}
各 Shot 按自己的景别、机位与视点构图；同一 Shot 保持连续。
No captions, subtitles, timecode, or watermark inside the images.
```

发送前把示例中的合写项展开为四个完整 Panel；跨请求须描述实际可见主体、位置、方向和状态，不只写“同上一镜”。`required_text[]` 是画内内容；无字幕/时间码约束不禁止必要画内文字。

## 画面与文字审阅

按项目画面标准判断每格是否对应当前口播并增加信息。镜头变化有动机，同镜头连续状态可保持构图；不强迫一镜到底，也不强迫四格四机位。

有文字时让一个主文字焦点正面、巨大、高对比，缩略审阅仍可读；删除抢注意力的无关角色、道具与并行动作。精确中文、命令和界面字段须逐字给出并审阅，镜头留稳定停留。文字不准时只修订受影响板，必要时缩短文字、简化场景并按影响重获批准；不得以真实截图、录屏、可控 UI 或后期叠字替代。

## Manifest 与锚点

顶层 `schema_version: 3.0`，`generator: codex-imagine`；`shots[]` 每单元记录：

- `shot_id` 与 `boards[]`；每板包含 `board_id / raw_board / review_board / imagine_prompt / panels[]`，恰好四项 Panel，提示词路径留档。
- `generation_images[]`：由获批 Panel 得到的 3–5 张干净图，不含边框、箭头、时间码、底栏。
- `generation_anchor_times_seconds[]`：与图一一对应、按信息/物理状态变化选择的语义时间，不能均匀铺帧；相邻轻微位移合并。整期图数不超过 `ceil(4.1 × 镜头数)`。
- 肯定式 `h3_visual_guard`，以及由 `broll-video prepare-h3-prompts <task-id>` 写入的 `h3_request_prompt`。

脚本与图片、锚点时间属于同一批准快照。不要手写大段示例 JSON 代替实际产物，也不手改生成脚本；正式字段要求由 schema 和阶段批准命令检查。
