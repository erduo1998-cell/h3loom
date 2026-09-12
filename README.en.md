<div align="center">

# H3Loom

### Turn a cloud model into your own video creation studio.

[简体中文](README.md) · **English** · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

[![Python](docs/images/badges/python.svg)](pyproject.toml)
[![Agent Skills](docs/images/badges/skills.svg)](.agents/skills/srt-broll-producer/SKILL.md)
[![Runtime](docs/images/badges/runtime.svg)](docs/autodl-production.md)
[![Status](docs/images/badges/status.svg)](https://github.com/erduo1998-cell/h3loom/releases/tag/v0.2.0rc1)
[![License: Apache-2.0](docs/images/badges/license.svg)](LICENSE)

**Your own cloud deployment · Ongoing generation experiments · A personal visual style**

</div>

Deploy your own cloud instance of MiniMax H3. Through repeated experiments, production, and review, build a collection of reliable reference images, camera techniques, and generation methods—and develop a personal style you can use again and again.

**For creators who want to make AI videos over the long term and are willing to refine their style through practice.** The current workflow turns narration SRT files into standalone 4K B-roll clips, with an Agent handling shot design, storyboards, and cloud execution.

> H3Loom is an independent MiniMax H3 cloud creation toolkit (H3 + loom). The first public release is **v0.2.0rc1**. Original code and the three Skills use [Apache-2.0](LICENSE). Model terms have separate territorial and commercial conditions; see [third-party notices](THIRD_PARTY_NOTICES.md). Fresh GPU installation and end-to-end generation still need hardware validation; see [release validation](docs/release-readiness.md).


### 24-second introduction · made with code

[![24-second introduction · made with code](docs/media/h3loom-intro-poster.png)](https://erduo1998-cell.github.io/h3loom/)

[Play MP4](https://erduo1998-cell.github.io/h3loom/) · [Source and build instructions](media/intro/README.md)

Locally rendered geometry, animation and synthesized sound. The silver module is a metaphor for the runtime, not physical hardware or an H3 generation sample.


![A cycle of cloud deployment, generation experiments, human review, and personal style](docs/images/style-loop.png)

<p align="center"><sub>01 Your own cloud environment → 02 Repeated generation experiments → 03 Selection and review → 04 Develop your personal style, then apply it to the next production</sub></p>

## 🎯 Why this project exists

One generation produces a video; sustained production helps you develop your own methods. Running the model on a server you rent lets you experiment with subjects, materials, colors, lighting, framing, and movement in a consistent environment. Keep what works and gradually reduce trial and error.

The workflow helps you build three kinds of assets:

| What you build | How it helps the next production |
| --- | --- |
| **Your own visual references** | Consistent characters, materials, colors, and lighting help maintain a coherent style across videos. |
| **Your own experience with shots and prompts** | Learn which combinations of scenes, actions, and camera choices are more likely to produce the results you want. |
| **Your own production and selection process** | Approve storyboards before generating videos, record problems, and carry improvements into the next round. |

The aim is more consistent output and a gradually higher success rate for usable footage. **This project does not include training or fine-tuning. Generating more videos does not automatically change the model weights.** Improvements come from the references, storyboards, prompts, and review experience that you and the Agent build together.

## 🎬 From narration to standalone video clips

![A three-stage workflow of shot design, four-panel storyboards, and cloud generation](docs/images/workflow-v2.png)

<p align="center"><sub>01 Design shots → 02 Approve storyboards → 03 Generate and download in the cloud. Both introduction images are AI-generated conceptual illustrations, not examples of actual H3 video output.</sub></p>

| Stage | What you and the Agent do together | Skill |
| --- | --- | --- |
| **01 · Design shots** | Read the complete SRT, content style references, and references for visual continuity with the talking-head footage; define scenes, coverage intervals, and camera beats. | [srt-broll-producer](.agents/skills/srt-broll-producer/SKILL.md) |
| **02 · Approve storyboards** | Use exactly four panels per board. Approve 1–2 samples before producing the full set, then select 3–5 clean anchor images per unit. | [broll-storyboard-producer](.agents/skills/broll-storyboard-producer/SKILL.md) |
| **03 · Generate and receive clips** | Compile requests from approved storyboards, generate, download, and recover tasks on AutoDL, then review the videos manually. | [h3-video-runtime](.agents/skills/h3-video-runtime/SKILL.md) |

The visual lock and shot plan, samples, and complete storyboards each require user approval. Execution then follows the approved budget. By default, the deliverables are **standalone 4K clips of 4–15 seconds each**; the workflow does not automatically edit them into a complete narration video. Stage two requires the Codex host's `imagegen` capability.

[View the complete three-stage workflow](docs/three-stage-workflow.md) · [View the installation and operations guide](docs/getting-started.md)

## 💰 Actual costs: compute + ongoing storage

The figures below are **production experience and budget estimates supplied by the author, recorded on 2026-09-07**. They are not a universal live platform quote, and the same costs are not guaranteed for every task. All amounts are in Chinese yuan (CNY).

| Item | Author's observations / basis currently used | How to budget |
| --- | --- | --- |
| **Video generation** | About **CNY 0.10 / second** | Calculated from the total duration of all generated videos, including candidates that were not selected. The cost per second of the final selected footage may be higher. Ongoing storage is additional. |
| **GPU server** | About **CNY 6 / hour** | Based on actual server time. Initialization, waiting, and repeated attempts also consume powered-on time. |
| **One production example** | **20 shots, about 2 hours; the author reported a cost of about CNY 10** | At CNY 6 × 2 hours, allow **about CNY 12**. The reported experience and the estimate based on the hourly rate are recorded separately. |
| **Ongoing asset storage** | About **CNY 3 / day**, or **CNY 90 / month** for 30 days | Keeping cloud models and assets incurs an ongoing cost that should have its own line in the monthly budget. |

**If you keep the assets for a full month and run just one 20-shot task like the example above, the sample budget is CNY 90 + CNY 12 ≈ CNY 102.** This calculation assumes the stated storage footprint, 30 days of storage, and 2 hours of compute. It is not a package price, and it does not fold every expense into “CNY 0.10 per second.”

Total spending also depends on charges for image generation, Agent subscriptions, and any other services you use. After shutting down the GPU, separately check whether the platform is still retaining and charging for storage. Stopping generation does not mean all charges stop. When complete billing evidence is unavailable, the program leaves actual costs pending verification; estimates are not presented as paid invoices.

## 🚀 What to prepare

- **Local machine**: Codex with built-in image generation, Python 3.11+, FFmpeg/FFprobe, and OpenSSH. Password-based SSH also requires `sshpass`. Your local machine does not need an NVIDIA GPU.
- **Cloud server**: The current deployment materials target AutoDL's RTX PRO 6000 Blackwell 96GB, with at least 120 GiB of RAM and 320 GB of available persistent storage. The eight models total about 156.45 GB.
- **Creative inputs**: A complete narration SRT, content style references, references for continuity with the talking-head footage, and a budget for this generation task.

Once you have repository access, clone and install it locally:

```bash
git clone https://github.com/erduo1998-cell/h3loom.git h3loom
cd h3loom
uv sync --frozen
source .venv/bin/activate
```

Without uv, create an environment with `python3 -m venv .venv`, activate it, and run `python -m pip install -e .`. Open the cloned directory in Codex and ask the Agent to read `AGENTS.md`. The project includes all three Skills, so there is no need to overwrite a global installation.

First check the entry point using synthetic subtitles, without permitting paid generation:

```bash
broll-video init --name "安装检查" --srt examples/demo.srt --ratio 16:9 --execution estimate_only
broll-video next <task-id>
```

Replace `<task-id>` with the task ID returned by the previous command. Before production, follow the [operations guide](docs/getting-started.md) to complete cloud deployment, visual approvals, and authorization for this task's budget. A new GPU deployment still requires validation on the actual hardware. This repository does not promise that arbitrary cloud providers, GPUs, or image generation backends will work out of the box.

## 💬 Paid consulting and founding membership

**Author: Liu Ran / Er Zong (刘冉 / 耳总). Consulting is a paid service.**

**Join the founding members' group to receive permanent eligibility for consulting.** For cloud deployment, video generation workflows, refining your personal style, or details about joining, scan the QR code to add the author's personal WeChat. Include **「MiniMax H3 种子会员」** in your request to discuss membership fees and the scope of consulting.

<p align="center">
  <img src="docs/images/wechat-qrcode.jpg" alt="Liu Ran / Er Zong's personal WeChat QR code for paid consulting and founding membership" width="260" />
</p>

<p align="center"><strong>Paid consulting · Founding members receive permanent eligibility for consulting</strong><br/>A personal consulting contact, not official MiniMax or AutoDL support.</p>

<p align="center"><a href="https://erduo.art">Personal website</a> · <a href="https://github.com/erduo1998-cell">GitHub @erduo1998-cell</a></p>

## 📚 Learn more

[Installation and operations guide](docs/getting-started.md) · [Production workflow](docs/three-stage-workflow.md) · [Migration scope](docs/migration-scope.md) · [Existing validation](docs/migration-validation.md) · [Third-party sources and license status](THIRD_PARTY_NOTICES.md)

Actual videos still require human review of visuals, text, and audio. See the [README asset record](docs/readme-assets.md) for the sources and display purposes of the introduction images and personal WeChat QR code.
