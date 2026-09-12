# 本地 Three.js 导出

这是当前首页 Three.js 影片的本地制作目录；旧 Blender 制作工程保留在 `media/intro/`。浏览器只执行本仓库手写场景，不调用云端 AI，不使用 Remotion 或 HyperFrames。

## 运行

需要 Node.js、FFmpeg、Google Chrome，以及 macOS 的 DIN Condensed Bold / Arial 系统字体。

```sh
cd media/intro-three
npm ci --ignore-scripts
npm run serve
```

预览地址 `http://127.0.0.1:8790/`。服务器仅监听本机；`PORT` 可覆盖端口。

从仓库根目录运行导出（导出器会自动开启临时端口，无需手动启动预览服务器）：

```sh
node media/intro-three/render.mjs --stills=0.5,2,4,8,12,18,23
node media/intro-three/render.mjs --start=0 --duration=4 --fps=60 --output=outputs/intro-three/sample.mp4
node media/intro-three/render.mjs --fps=60
```

默认影片输出 `outputs/intro-three/h3loom-type-study.mp4`，1920×1080、60 fps（以场景默认 fps 为准）、H.264 CRF 18，**无音轨**。输出不会修改 `docs/media/` 中已发布影片。`--output` 的相对路径始终相对仓库根目录，重复运行会覆盖指定的实验输出。

`--frames=120` 可限制输出帧数；`--width=1280 --height=720` 可降低预览分辨率；`--save-frames` 保留 PNG；`--crf=20` 调整编码质量。`--stills=0.5,2` 只输出指定时间 PNG，不编码影片。PNG 在与影片同级的 `<影片文件名>-frames/` 目录。视频可通过预览服务器的 `/outputs/intro-three/` 路径回放。

## 场景契约

`index.html` 加载浏览器 ESM 场景，并提供：

```js
window.film = {
  duration: 24,
  fps: 60,
  ready: true,
  renderAt(seconds) { /* 同步更新所有状态并渲染；也允许返回 Promise */ }
};
```

导出器访问 `/?render=1&width=1920&height=1080`。该模式应停止自动播放；`renderAt(t)` 必须由绝对时间决定所有画面状态，不能依赖上一帧或墙钟。第一个 canvas 的 CSS 尺寸必须等于查询参数的像素尺寸；建议左上定位。导出器按照 canvas 的实际边界截图，避免把播放器按钮编码进去。

每帧调用 `renderAt(start + frame / fps)`，再通过 Chrome 的页面合成截图读取 PNG，依次流入 FFmpeg。帧时间由代码固定，不受实时播放掉帧影响。`--duration` 仅裁剪输出时间范围，不改变动画速度。

系统字体通过 `/fonts/display.ttf` 与 `/fonts/label.ttf` 本地映射读取，不复制或重新分发字体文件。若在非 macOS 平台运行，需要调整 `serve.mjs` 的字体映射，使用自行取得授权的字体。

## 已核验环境与限制

2026-09-12：固定 npm 版本 `three@0.186.0`、`playwright-core@1.63.0`、`opentype.js@1.3.4`。TTFLoader 的 CDN 导入须在 HTML import map 映射到本地 opentype 模块，导出期间阻止外部依赖请求。Chrome 实际创建 WebGL 2 上下文，报告：

```text
ANGLE (Apple, ANGLE Metal Renderer: Apple M5 Pro, Unspecified Version)
WebGL 2.0 (OpenGL ES 3.0 Chromium)
```

因此当前机器使用 Metal GPU 路径；这不等于离线导出能实时达到 60 fps。总速度还受场景复杂度、截图传输与 H.264 编码影响。每次实际导出会写入 `<输出>.json`，记录帧数、时间范围、GPU 字符串、浏览器版本和实测吞吐量。`--software` 显式改用 SwiftShader，仅用于诊断；默认不会把软件渲染伪报为 GPU 渲染。

本次场景的 13.2–15.2 秒排版片段已完成实际短样验证：1920×1080、60 fps、120 帧，渲染加编码用时 3.249 秒，约 36.9 帧/秒（不含 Chrome 启动和字体初始化）。FFprobe 确认 H.264、2.000 秒、120 帧，FFmpeg 全帧解码无错误。这是该两秒片段的局部数据，不能直接作为复杂场景或其他设备的速度承诺。

`CHROME_EXECUTABLE`、`FFMPEG` 可指定本机可执行程序。此导出器不会下载 Chromium，不会安装全局 npm 包，不会上传影片。
