# 第三方来源与许可

H3Loom 是独立的工作流与部署工具。自有代码、三个 Skill 和文档的发行许可仍待所有者决定；本地候选尚未公开。任何未来的自有代码许可都不覆盖模型、上游代码、NVIDIA 二进制文件或个人身份素材。

## 模型条件

本项目只保存下载清单，不再分发权重。八个模型使用固定的 Comfy-Org/MiniMax-H3 revision，来源、大小和 SHA-256 见 [模型清单](deploy/model-manifest.json)。

2026-09-12 核对了该模型仓库的许可证声明，并保存官方 MiniMax H3 许可与 FAQ 的固定提交版本：[许可全文](licenses/MINIMAX-H3-LICENSE.txt) · [官方 FAQ](licenses/MINIMAX-H3-QA.md)。原始 URL 与 SHA-256 见 [来源记录](licenses/sources.json)。

使用前请阅读全文，特别注意：

- 许可定义的 Territory 排除欧盟、英国、韩国和美国；翻译文档不改变允许使用的地区。
- 商业使用需要遵守通知、品牌展示及其他条件。年商业收入超过 2,000 万美元时需要事先取得许可方书面授权。
- 分发相关模型材料或衍生内容时适用的协议传递、归属声明与其他义务，以许可原文为准。
- 本项目没有取得可替代模型条款的授权，不能以未来的代码许可证推断模型在全球或所有用途均可自由使用。

这些是供安装前定位条款的提示，不扩大上游授权。配套组件如有独立条款，仍分别适用。

## 软件与二进制来源

| 内容 | 版本及来源 | 保存方式与许可 |
| --- | --- | --- |
| H3 Easy | commit `33b6a795ea8f53354eb6b7854a731be49ef24a4e` | 小型源码包；原始 MIT LICENSE、manifest、SHA256SUMS 保留。[归档来源](deploy/h3-easy-source.json) 记录仅清理打包元数据，源码字节未变。 |
| H3Keyframes | commit `9bce864b7df056a2822e4af593de17ef199ebcdc` | 最小节点子集，保留 [MIT LICENSE](deploy/h3-keyframes-only/LICENSE) 与 [来源](deploy/h3-keyframes-only/SOURCE.json)。 |
| ComfyUI | 固定提交见 [安装器](deploy/install-stack.sh) | 部署时获取上游源码；[GPL-3.0 原文](licenses/ComfyUI.txt)。本仓库保留的补丁不改变上游许可。 |
| KJNodes | 固定提交见安装器 | 部署时获取；[GPL-3.0 原文](licenses/KJNodes.txt)。 |
| NVIDIA RTX Nodes | 固定提交见安装器 | 部署时获取；[Apache-2.0 原文](licenses/NVIDIA-RTX-Nodes.txt)。 |
| NVIDIA VFX | `nvidia-vfx 0.1.0.1` | 仅保留 [官方下载 URL、版本与哈希](deploy/nvidia-vfx-source.json)，不包含 wheel，也不声称取得再分发权。使用受 NVIDIA 适用条款约束。 |
| 其他 Python 依赖 | [云端固定清单](deploy/cloud-requirements.txt) 与 [本地锁文件](uv.lock) | 安装时获取，各依赖保留自身许可。固定版本不等于获得额外使用或再分发授权。 |
| Codex imagegen | 用户自己的 Codex 宿主 | 外部服务能力，未复制系统 Skill、服务实现或凭据；按宿主条款与可用性使用。 |

## 文档与宣传素材

[README 素材记录](docs/readme-assets.md) 分别记录概念图和作者微信二维码的来源。个人二维码、姓名及咨询身份不属于供他人冒用的通用品牌资产。

项目介绍视频采用本地手写代码渲染；字体来自操作系统，不随代码再分发。参考片只用于观察排版与运动设计，不包含其视频、音乐或 Apple 标识。视频中的云端模块是概念模型，不能作为实体硬件或 H3 生成质量的证明。
