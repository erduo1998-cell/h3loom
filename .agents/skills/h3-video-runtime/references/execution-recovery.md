# 执行与恢复

恢复、失败、缺下载、换机或交棒时读取相关部分。

## 恢复真源

在 `work/tasks/<task-id>/` 读取 `task.json` 与 `broll-video next <task-id>` 指出的当前产物；相关请求位于 `h3-requests/<shot-id>/attempt-NNN/`，provider 收据在 `provider/autodl/`。不要扫描全部旧任务或从聊天重建状态。

按现有证据处理：

1. `result.json` 与有效非空下载已存在：复用。
2. `task-id.txt` 有 `prompt_id`：只查询该 ID；成功未下载则补下载。
3. 本地 ID 文件缺失：按 request 指纹查 provider 记录，恢复已有 ID。
4. `/prompt` 结果不确定且仍找不到 ID：保留 reservation/provider 状态并停止，不自动重提。实例关机或 SSH 中断不代表生成失败。

恢复原任务使用 `broll-autodl run-batch <task-id>`，由已有状态决定继续、查询或补下载。只有原批准集合内尚未提交的请求可继续；额外抽卡、变参、新 task 或新 attempt 不能绕过失败与授权记录。

## 换机与接力

用户明确确认旧实例不可恢复并授权换机后才执行：

```bash
broll-autodl authorize-replacement <task-id> --shot-id <shot-id> --attempt <attempt-NNN> --reason '<reason>' --recovery-evidence '<evidence>'
broll-autodl replace-live-attempt <task-id> <authorization-id>
broll-autodl plan-batch <task-id>
```

先安装当次目标实例凭据。新 attempt 绑定该目标实例完整 context；实际运行实例不符则停止。永久保留旧 attempt、ID、provider 记录和结果，新结果仍须经过 delivery 与人工 `accept`。

同一实例只能有一条生成线。接棒另一任务/会话前，只读确认前置任务生成终态、下载/收据完成、主进程退出且 Comfy 无运行/等待 prompt；这是交棒检查，不加入日常每条生成流程。任务级不关机策略只可依据明确接力授权写入，不能改共享默认。

## 预算、收货和关机

- `estimate_only` 只估价；执行授权与额度以本期 `task.json` 为准，默认 20 CNY，用户明确授权最高 50 CNY。规划占用不等于实际花费；缺平台账单起止证据时 `spent` 保持 `pending`，保守估算继续占用预算。
- 生成线、下载/收据线和 `delivery-manifest.json` 全部完成后才关机或交棒。异常时暂停新提交，保留实例供恢复并说明可能仍计费。
- 默认执行一次远程 `/usr/bin/shutdown`，确认当次 SSH endpoint 不可达并保存收据；未证实时报告 `shutdown_unverified`。不可连接不能证明平台计费已停止。
- 原始下载存 `outputs/generated/<task-id>/`，当前候选存 `outputs/final/<task-id>/`；原始文件不能被转码版覆盖。输出 SHA、快速媒体检查与人工审片状态写入结果及 delivery，不自动添加深度 QC 或付费重抽。
