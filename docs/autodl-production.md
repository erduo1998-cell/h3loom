# AutoDL 生产运行说明

生产后端为 AutoDL `pro6000-p`、RTX PRO 6000 96GB。已验证的日常链路直接执行；安装、迁移和故障诊断才读取相应底层材料。

## 日常入口

准备好已批准故事板与脚本，并在 `task.json` 记录执行范围与预算；关机时优先完成本地编译和规划，已有运行实例不为计划反复开关机：

```bash
broll-video compile-h3 <task-id>
broll-autodl plan-batch <task-id>
```

`plan-batch` 冻结请求哈希、工作流、预算与 `live-run.json`。用户手动开机后执行：

```bash
broll-autodl run-batch <task-id>
```

它使用已有计划，启动 Comfy/隧道，上传、提交或恢复、并行下载和写收据，完成后按任务策略关机。正常启动不重复检查 `/system_stats`、平台、Git、Torch、Sage、节点与模型。失败时沿已有 ID 恢复，不把断线或实例关机当重新提交授权。

## 连接、迁移与恢复

- 新克隆、实例变化、endpoint 变化或凭据失效：使用当次实例卡片 SSH 命令与密码运行 `broll-autodl install-credentials`。只有同一已验证实例会话可复用凭据；相同 host/port 不足以证明实例未变。密码在本地安全输入，勿发聊天。
- 安装或镜像、Comfy、节点、模型、工作流变化：执行 `broll-autodl verify-stack`，保存并批准新 fingerprint。完整绑定见 [API 与生产契约](../.agents/skills/h3-video-runtime/references/api-contract.md)。
- 缺下载、不确定提交、换机或跨任务接力：查 [执行与恢复](../.agents/skills/h3-video-runtime/references/execution-recovery.md)。
- 从零部署或跨云迁移：查 [迁移契约](h3-stack-portability.md)，不以无卡盘点冒充有卡验收。

## 成本与完成

预算依据 [task.json 授权契约](three-stage-workflow.md#任务与授权契约)。项目历史实测计划价为 5.98 CNY/小时，只用于保守占用；价格变化按本期证据更新。账单起止证据不足时 `spent` 保持 `pending`，记录生成耗时、session 秒数及可证明的分摊成本，不以估算冒充实花。

生成线、下载/收据线和 delivery 全部完成后，默认一次远程关机并记录 SSH 不可达证据；它不能证明平台账单已停止。失败保留实例供修复，并报告可能持续计费及恢复状态。明确授权接力时才使用任务级不关机策略。
