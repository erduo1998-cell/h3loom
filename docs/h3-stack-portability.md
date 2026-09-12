# MiniMax H3 跨云迁移与恢复契约

目标不是复制某一家云厂商的整台机器，而是同时保留两种恢复能力：

1. **原样恢复**：保留 AutoDL 数据盘或平台镜像，作为最快的灾难恢复路径。
2. **跨云重建**：以代码、固定版本、模型清单、哈希、工作流和验收收据，从一台干净 GPU 主机重新部署。

## 四层交接包

| 层 | 本地保存内容 | 不应混入 Git 的内容 |
| --- | --- | --- |
| 控制层 | 安装器、启动器、下载器、工作流编译器、生产 CLI | SSH 密码、Token |
| 依赖层 | OS/CUDA/Python/PyTorch、ComfyUI 与节点固定提交、pip 锁定清单 | 临时缓存 |
| 模型层 | 文件名、来源、许可、字节数、SHA-256；可选离线冷备 | 未确认再分发权的公开发布包 |
| 证据层 | 无卡盘点、GPU full verify、4K smoke、最小 H3 canary 收据 | 用户素材、生成历史和私人输入 |

模型权重单独管理。Git 只保存 manifest 与校验值；如需完全离线恢复，再把约 156.45 GB 的八个生产权重复制到加密移动硬盘或对象存储，并保存第二份校验清单。

## 当前已知事实

- 当前生产机使用 `/root/autodl-tmp/h3-stack`。2026-09-06 的无卡实机盘点证明，生产栈实际由八个模型组成，共 156,450,873,596 bytes；逐文件 SHA-256 全部通过。生产清单位于 `config/autodl-production-models.json`。
- 早期 172 GB 清单中的 NVFP4 文本编码器只是 BF16 失败时的候选回退，未安装在跑通的生产机上，不属于默认部署。
- 已知生产指纹固定了 ComfyUI、KJNodes、NVIDIA RTX Nodes、H3 Easy、H3Keyframes、Torch/CUDA 与模型收据。
- 当前小型部署材料以仓库 `deploy/` 为移交真源，原生产目录中的临时备份和运行记录不属于发行包。
- 早期安装器强绑定 AutoDL 路径、RTX PRO 6000 Blackwell、120 GiB 内存和 AutoDL 自带 Miniconda；跨云版本必须把这些拆成“硬件能力要求”和“云厂商适配层”。

## 两次验证

### 无卡盘点

无卡模式可完成系统、磁盘布局、Python 包、ComfyUI/节点提交、非 Git 节点树哈希、模型字节数与 SHA-256、启动脚本和历史收据盘点。命令只读取服务器：

```bash
python scripts/audit_autodl_h3_stack.py --project-root . --hash-models
```

结果写入 Git 忽略的 `work/stack-audits/<UTC>/`，不会收集密码、Token、环境变量、shell history、输入素材或生成结果。

## 从仓库导出移交副本

本仓库的 `deploy/` 已保存可移交的小型部署材料，三个 Skill 与全部本机运行代码也在同一仓库。无需依赖原生产空间的 `work/` 目录或旧备份脚本。

在完成提交后，可导出该提交的完整源码包：

```bash
git archive --format=tar.gz --output=../minimax-h3-source.tar.gz HEAD
```

这只导出已提交文件，不包含被忽略的私人任务、凭据、素材、模型或 NVIDIA wheel。它是源码与部署材料包，**不是完全离线安装包**。默认模型与 NVIDIA wheel 仍按仓库 manifest 联网下载；完全离线恢复还需另行备齐这些依赖。

### 有卡验收

迁移或新建实例后，再运行现有 full verify，并保存新黄金指纹：

```bash
broll-autodl verify-stack
```

最终迁移验收必须同时证明：GPU/驱动与 CUDA 能力满足要求、节点 socket 与冻结工作流一致、4K RTX smoke 通过，以及一次经授权的最小 H3 canary 能生成、下载和恢复。没有 GPU 的盘点不能替代这一层。

## 跨云重建的最终完成定义（尚未全部验证）

只有满足以下条件，才能称为“另一个 AI 可以接手部署”：

- 全部小型部署资产进入稳定仓库并有总 manifest；
- 八个生产模型均有来源、许可、字节数和 SHA-256，且至少有一种可访问的恢复来源；
- AutoDL 与通用 Linux GPU 主机分别只有一个入口命令；
- 在一台干净实例上完成从零部署，而不是从旧数据盘启动；
- full verify 与最小生成 canary 都产生可核对收据；
- 密钥永远由接手者在本机安全输入，不出现在文档、命令行和仓库。
