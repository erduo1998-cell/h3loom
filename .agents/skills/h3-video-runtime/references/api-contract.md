# AutoDL + ComfyUI 生产绑定

首次执行、连接变化或诊断绑定问题时查本文件；例行恢复不必重读。

## 连接与凭据

生产后端为 AutoDL `pro6000-p`、RTX PRO 6000 96GB，用户手动开机。SSH/loopback `127.0.0.1:8188` 使用已验证启动脚本及 `/upload/image`、`/prompt`、`/history/{prompt_id}`、`/view`；`/system_stats`、`/object_info` 和 `/queue` 不进入正常生成主链。

新克隆、实例变化、endpoint 变化或旧凭据失效时执行：

```bash
broll-autodl install-credentials
```

只输入当次实例卡片 SSH 命令与密码；安装器锁定 host key。密码保存在 owner-only `secrets/autodl.local.json`（0600），仅通过继承文件描述符交给 `sshpass`；不进入 argv、环境、任务、日志、远端或对话。host key 保存在 owner-only `~/.config/broll-autodl/known_hosts`。

只有同一已验证实例会话可复用本地凭据，相同域名、host/port 或 host key 都不足以独自证明仍是原实例。不将旧密码自动发给新 endpoint，不要求用户提供 Token、UUID 或 fingerprint。

## 验证触发条件

日常只依赖已验证启动脚本确认服务可用，不重复读取 Git、Torch、Sage、模型、补丁或完整节点表。安装、镜像、Comfy、节点、模型或工作流发生变化时运行 `broll-autodl verify-stack`，保存新的 full verify 收据并由用户批准黄金 fingerprint 后再提交。

黄金 fingerprint 绑定实例/GPU、Comfy commit、节点/模型 SHA、工作流与编译器版本、必要 socket/object-info 和 4K RTX smoke；不在文档硬编码哈希。任务 fingerprint 另绑定批准故事板字节、prompt、时长、画幅、分辨率、profile 与 seed。只有真实栈变化或证据失效才重做对应验证。

## 编译与声音

阶段二 `h3_request_prompt` 最长 1600 字符，阶段三确定性复现与校验后装入官方 FL2VA 结构：

```text
How the reference pictures align...
integrated_multimodal_description: <已冻结的时间、动作、摄影与过渡>
overall_soundscape: <本镜头同步环境声与可见动作音效>
non_diegetic_music: N/A
```

图片负责主体、空间、构图、材质、光色和画内文字。锚点按 `generation_anchor_times_seconds` 映射 H3Keyframes 绝对帧，不均匀铺成 0%–100%。上传和 `/prompt` 前由代码复查批准字节、请求一致性、口播原文字段泄漏与 SFX-only；合法时间码与视觉描述不因关键词被排除。

`dry-run --request /absolute/path/request.json` 用于单请求离线诊断；`export-final-conditioning <task-id>` 用于检查最终声音或脚本问题。它们是定向诊断工具，不是 `plan-batch` 后的重复必做流程。M4 后期叠字路线仍为 `forbidden`。
