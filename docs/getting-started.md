# 安装与完整运行手册

[返回项目介绍](../README.md)

# H3Loom 三阶段视频生成工作流

从完整口播 SRT 出发，由 Agent 设计镜头、生成四格故事板，再通过 AutoDL 上的 MiniMax H3 生成独立 4K B-roll 素材。本仓库包含三个自研 Skill、运行代码、配置、数据结构、测试和云端部署材料。

**首个公开版本为 v0.2.0rc1，自有代码与三个 Skill 采用 [Apache-2.0](../LICENSE)。新 GPU 从零部署及完整生成尚待实机验收。** 模型、NVIDIA wheel、密码、用户素材与生成结果不进入仓库。

## 三个阶段

| 阶段 | 主 Skill | 输入 → 交付 |
| --- | --- | --- |
| 1. 镜头设计 | [srt-broll-producer](../.agents/skills/srt-broll-producer/SKILL.md) | 完整 SRT、内容风格参考、口播衔接参考 → 视觉锁、覆盖区间、具体场景与摄影节拍 |
| 2. 故事板 | [broll-storyboard-producer](../.agents/skills/broll-storyboard-producer/SKILL.md) | 已批准镜头计划 → 四格样板、全量故事板、3–5 张锚点与冻结的 H3 生成脚本 |
| 3. 视频执行 | [h3-video-runtime](../.agents/skills/h3-video-runtime/SKILL.md) | 已批准故事板 → 官方结构编译、预算计划、AutoDL 生成、下载、恢复与交付收据 |

完整流程及各阶段读取的文件见 [三阶段生产流程](three-stage-workflow.md)。每阶段只加载一个主 Skill；阶段二实际生图时临时加载宿主提供的 `imagegen`。

这是一条由 Agent 完成设计与图片生成、由 Python 程序管理批准和执行的工作流。安装 Python 包不会自动获得图片生成能力。当前图片后端固定为 Codex Imagine；需要具备内置生图能力的 Codex 环境。普通终端可以管理任务、校验与执行 H3，但不能独立完成前两阶段创作。

## 本机安装

需要 Python 3.11+、FFmpeg/FFprobe、OpenSSH（`ssh`、`scp`、`ssh-keyscan`、`ssh-keygen`）；密码 SSH 另需 `sshpass`。本机不需要 NVIDIA GPU。云端要求见下文。

克隆公开仓库，并在仓库根目录安装锁定依赖：

```bash
git clone https://github.com/erduo1998-cell/h3loom.git h3loom
cd h3loom
uv sync --frozen
source .venv/bin/activate
broll-video --help
broll-autodl --help
```

没有 uv 时可用 `python3 -m venv .venv`，激活后 `python -m pip install -e .`；此方式按 `pyproject.toml` 解析依赖，不保证与 `uv.lock` 的版本逐项相同。

在 Codex 中打开**该克隆目录**，读取 `AGENTS.md`，即可使用 `.agents/skills/` 下的项目 Skill，无需覆盖全局 Skill。若宿主未自动发现，明确让 Agent 读取上述 Skill 文件。命令在仓库根目录执行；从别处执行需把 `--project-root /absolute/path/to/clone` 放在子命令前。`--srt` 等输入路径仍相对于当前目录，从别处运行时使用输入文件的绝对路径。仅安装 wheel 不会安装根目录配置、Skill 和 schema，因此目前支持的完整安装方式是 clone + 项目内安装。

## 开始一个任务

仓库附带的 [demo.srt](../examples/demo.srt) 是专为安装检查编写的合成输入，不含真实口播。先创建一个不允许付费生成的任务：

```bash
broll-video init --name "安装检查" --srt examples/demo.srt --ratio 16:9 --resolution 4K --budget 20 --execution estimate_only
broll-video next <task-id>
```

新任务会进入 `work/tasks/<task-id>/`，并提示进入第一阶段。`init` 创建 `task.json` 和 SRT 副本；视觉锁、计划及故事板由对应阶段陆续写入，不会在初始化时凭空生成。两类真实参考缺失时，Agent 应向用户取得参考后再做设计。[任务模板](../templates/TASK_TEMPLATE.json) 只供字段阅读，实际任务以 `init` 创建的文件为准。

接下来让 Agent 使用 `srt-broll-producer` 处理 SRT。流程保留三次视觉确认：视觉锁与完整镜头计划 → 1–2 个故事板样板 → 全量分镜。收到对应用户批准后才记录：

```bash
broll-video approve-shot-plan <task-id> --approval-source explicit_user_instruction
broll-video approve-storyboard-sample <task-id> --approval-source explicit_user_instruction
```

第二阶段完成全量图后，先生成脚本，再由用户确认分镜：

```bash
broll-video prepare-h3-prompts <task-id>
broll-video approve-storyboards <task-id> --approval-source explicit_user_instruction
broll-video compile-h3 <task-id>
```

批准绑定文件 SHA-256；改图、改计划或改脚本后需按所处阶段重新确认。每个单元生成一条连续 4–15 秒素材，固定 precision、4K、SFX-only，默认两抽；单抽只接受任务明确授权。默认预算上限 20 CNY，用户明确授权时最高 50 CNY。文件级检查不能代替人工审片，也不能证明模型音轨一定没有人声或音乐。

## 云端部署与生成

已记录的生产栈为 Ubuntu 22.04 x86_64、RTX PRO 6000 Blackwell Server Edition 96GB、至少 120 GiB RAM 与 320 GB 可用持久盘；ComfyUI `v0.33.1` / `72865f4f27eaf5396f8f36370e0a2be3a9a090ee`、PyTorch `2.11.0+cu130`。八个模型合计 `156,450,873,596` bytes，固定来源与 SHA-256 见 [生产模型清单](../config/autodl-production-models.json)，栈版本见 [栈指纹](../config/autodl-stack-fingerprint.json)。

1. 使用当前实例 SSH 命令和密码运行 `broll-autodl install-credentials`。密码在本机安全交互输入，不发到聊天，不放进 GitHub 或 GPU 上的 Git 凭据。
2. 将 `deploy/` 的**内容**上传到服务器 `/root/autodl-tmp/h3-stack/incoming/`；在该目录运行 `bash install-stack.sh`，再运行 `/root/autodl-tmp/h3-stack/env/bin/python download-models.py model-manifest.json`。
3. 用 `bash launch-comfy.sh` 启动，再运行 `/root/autodl-tmp/h3-stack/env/bin/python probe-stack.py --smoke-rtx-4k` 检查节点输入与 4K VFX 帧。
4. 本机运行 `broll-autodl verify-stack`，保存新实例的核验记录。新机仍需经用户授权的最小视频生成、下载、恢复及关机验收；仓库测试不能替代 GPU 实机验收。

下载器逐项核对八个模型的 SHA-256 后，原子写入 `receipts/models-verified.json`，并保留带时间戳的历史收据。稳定收据只包含模型身份，不含机器路径或日期；`verify-stack` 核对这份收据。旧实例升级需要重跑下载器以复核现有权重并建立新收据，已验证文件不会重复下载。不能手工复制旧黄金收据冒充验证。

云端 Python 依赖由 `deploy/cloud-requirements.txt` 固定，来源是生产栈实测包清单。当前修改经过本机测试，仍需新 GPU 实例验证完整安装和生成。

安装器当前只支持 AutoDL 的固定持久盘和 Miniconda 布局。换 GPU 或云平台需要适配并重新验证；不宣称已经支持任意云。模型和 NVIDIA wheel 在部署时联网下载并核对哈希，此仓库不是完全离线包。

用户已明确授权本任务预算后，才能记录授权并规划执行：

```bash
broll-video authorize <task-id>
broll-autodl plan-batch <task-id>
```

`plan-batch` 在关机状态冻结 `live-run.json`；用户手动开机后执行 `broll-autodl run-batch <task-id>`。恢复仍用同一入口，已有 `prompt_id` 不重新提交。执行使用一条生成线和一条下载/收据线，队列上限 4；全部完成后关机，失败时保留实例便于修复。计划价是带有效期的估算配置，不是实时平台报价；缺少平台账单证据时实际费用仍为 `pending`。

详细操作见 [AutoDL 生产说明](autodl-production.md) 与 [部署及恢复边界](h3-stack-portability.md)。

## 交付与维护

- `outputs/generated/<task-id>/` 保存原始下载，`outputs/final/<task-id>/` 保存当前候选；默认 `human_review_pending`，用户审片接受后才运行 `broll-video accept <task-id>`。
- `deploy/` 保存小型重建材料；`broll_video/`、`schemas/`、`tests_broll/` 保存执行逻辑、数据结构与测试。
- `work/`、`outputs/`、`secrets/` 均被 Git 忽略。升级时保留这些私人目录；不要把整个生产目录复制进发行仓库。
- [迁移记录](migration-scope.md) 说明哪些内容迁入、哪些历史或私人内容保留在原项目；[第三方来源与许可状态](../THIRD_PARTY_NOTICES.md) 说明代码许可与独立适用的第三方条款。

本机离线逻辑测试（不调用图片生成、云端或付费视频）：

```bash
python -m unittest discover -s tests_broll
```

维护 Skill 时还需使用所在 Codex 环境的 `skill-creator/scripts/quick_validate.py` 逐一校验三个 Skill；该工具属于宿主，不是本仓库自带程序。安装与迁移验证范围见 [验证记录](migration-validation.md)。
