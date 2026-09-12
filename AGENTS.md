# H3Loom

本仓库保存完整 SRT B-roll 三阶段流程和 MiniMax H3 / ComfyUI 云端部署材料，是独立工具，不是 MiniMax、AutoDL 或 OpenAI 官方产品。

## 工作方式

- 按用户语言简洁说明结果、依据与真实限制。明确的本地维护请求直接完成；按需读取文档与代码，不重复已经有效的检查。
- 保留无关的未提交改动、私人任务和凭据。删除用户数据、发布、付费生成和远端写入只在用户明确授权范围内执行。
- 不默认启动子 Agent；只有用户要求并行分工或明确允许时才使用。

## 三阶段生产

新任务使用 `agent-know-gold-v1` + `three-stage-four-panel-v1`，默认交付独立 H3 B-roll 素材，不自动扩展为完整成片或电商广告流程。生产只加载当前阶段入口；审计、文档和代码维护不受此限制。

1. `.agents/skills/srt-broll-producer/SKILL.md`：完整理解 SRT，取得内容风格和口播衔接两类参考，冻结视觉锁，设计具体场景，再规划覆盖区间与摄影节拍。
2. `.agents/skills/broll-storyboard-producer/SKILL.md`：依据获批计划按语义安排每单元 1–4 张四格板；先确认 1–2 个样板，再生成全量。实际生图时加载宿主 `imagegen`。
3. `.agents/skills/h3-video-runtime/SKILL.md`：确定性编译冻结脚本，在 AutoDL 生成、恢复、下载和交付。生产沿用已验证链路，安装、栈变化和故障诊断才检查对应环境。

视觉锁与完整镜头计划、故事板样板、全量分镜分别需要用户明确批准并按 SHA-256 冻结；自检不代替批准。有效批准及执行授权已具备时直接继续，不另加交接确认。任务关系、抽数和预算见 [任务与授权契约](docs/three-stage-workflow.md#任务与授权契约)，不得由聊天摘要、文件名或旧产物推断。

## 画面验收

- 关闭口播后，观众仍能凭画面与必要文字判断对象、问题或关系，跟上信息推进。动作段用动作与结果；抽象观点可用标题、对照、卡片、图标和空间关系，不把关键词贴在语义无关的画面上。
- 新 Shot 应有动机地改变景别、机位或视点并增加信息；轻微变化留在同一 Shot。
- `rhetorical_coverage` 逐项映射必需章节、问题、分类和回调，覆盖率不能代替完整性。
- B-roll 生成素材中的中文、终端与界面内容仍由 AI 生成；降低复杂度并在故事板逐字验收，不以截图、录屏或后期叠字替代。

## 安装与维护

完整安装使用 clone + 仓库根目录 `uv sync --frozen`；只安装 wheel 不包含根目录 Skill、schema 与配置。私人任务保存在 Git 忽略的 `work/`、`outputs/`、`secrets/`，升级不得覆盖。

云端限定 AutoDL / RTX PRO 6000 Blackwell Server Edition 96GB。部署按 [运行手册](docs/getting-started.md)、[迁移契约](docs/h3-stack-portability.md) 和 `deploy/` 的固定版本执行。`verify-stack` 核对版本与运行时收据，不能单独证明视频生成、下载、恢复和关机通过；新实例须留实机验收记录。模型使用遵守 [第三方许可](THIRD_PARTY_NOTICES.md)。

维护时运行受影响的 `tests_broll`；修改 Skill 同时检查三个入口与引用，发行候选执行 `python scripts/check_release.py`。不提交凭据、真实任务/日志、用户素材、模型权重或 NVIDIA wheel。

三阶段的生图与视频约束适用于 B-roll 生产任务。仓库介绍素材的制作方式遵从当次用户要求；手写代码的产品动画不冒充 H3 实际生成成片。
