# 技术架构

本文是开工前的提案，第 0 步（接口文档）完成后会更新。和 FretStudio 不同的地方都写明了原因。

## 运行时组成

```
              手机热点（同一个 Wi-Fi）
   ┌──────────────────────┐        ┌───────────────────────────────┐
   │ iPad（Safari / PWA）  │  HTTPS │ Raspberry Pi 5（不接屏幕）      │
   │  app/                │◄──────►│  server/   FastAPI             │
   │  - 四个视图           │  WSS   │  engine/   和声与编配           │
   │  - Tone.js 六轨播放   │◄──────►│  device/bridge  面板事件桥      │
   │  - 摄像头、麦克风     │        │  打印、定位                     │
   └──────────────────────┘        └──────┬───────────┬────────────┘
                                          │ USB       │ USB
                                   ┌──────▼─────┐ ┌───▼──────────┐
                                   │ 控制板      │ │ 热敏打印机     │
                                   │ firmware/  │ │ GPS 模块      │
                                   └────────────┘ └──────────────┘
```

- iPad 只做界面、播放和采集（摄像头、麦克风），不跑后端。
- Pi 跑后端、读控制板、驱动打印机和 GPS。
- iPad 上的 Safari 不支持 Web MIDI，所以控制板不直接接 iPad：Pi 读控制板，经 WebSocket 把事件转给网页，灯光状态反方向发回。
- 摄像头和麦克风要求 HTTPS：Pi 上用本地证书（如 mkcert），证书预先装到 iPad 上。

## 模块划分

| 目录 | 语言 | 职责 | 负责的代理 |
| --- | --- | --- | --- |
| `shared/schema/` | JSON Schema | 歌曲模型、面板事件、API 载荷的唯一定义；生成 Pydantic 和 TypeScript 类型 | 主代理 |
| `engine/` | Python | 纯函数库：和声候选、HRE 打分、ACS 可弹性、变调夹、和弦拼写、贝斯与鼓生成。不依赖 web 框架 | A 后端 |
| `server/` | Python | FastAPI：歌曲会话、操作历史（撤销、换一个）、锁定、生成接口、渲染适配层、哼唱转谱、卡片接口、定位、面板转发 | A 后端 |
| `app/` | TypeScript | iPad 网页：种子卡、整首歌、单轨编辑、卡片预览四个视图；六轨混音播放；扫码 | B 前端 |
| `device/bridge/` | Python | asyncio 服务：读 USB MIDI，发 WebSocket 事件，接收灯光状态 | C 设备 |
| `device/firmware/` | C++（Arduino） | Teensy 或 Pico 固件，用 Control Surface 库 | C 设备 |
| `device/simulator/` | Web | 屏幕上的二维面板，以面板身份连接 `/ws/panel`，硬件到货前代替控制板 | C 设备 |
| `device/card/` | Python | 卡片排版、离线风格化、热敏打印（`fretcase_card` 包，接口见 `docs/milestone-1.md`），由 `server/` 调用 | C 设备 |

`engine/` 从 `server/` 分出来，是 FretStudio 没有做的：FretStudio 里和声逻辑和 API、会话、日志混在 `server/` 下，测试和复用都要带上整个服务。

## 技术选型

| 方面 | 选择 | 和 FretStudio 相比 |
| --- | --- | --- |
| 歌曲的内部表示 | JSON 歌曲模型（六轨音符、和弦、歌词、每轨音量、锁定），Pydantic v2 定义 | FretStudio 用 ABC 字符串当状态，调号、空行、声部合并等问题反复出现。ABC、MIDI、MusicXML 改为只做导入导出 |
| 前后端共用类型 | JSON Schema 生成 Pydantic 和 TypeScript 类型 | FretStudio 前后端各算一套，出现过分数互相矛盾 |
| 播放 | Tone.js，每轨一个采样乐器和一个增益节点，推子直接控制增益 | abcjs 合成器适合单声部试听，做不了六轨混音和逐轨推子 |
| 后端框架 | FastAPI | 不变 |
| 前端框架 | React + TypeScript + Vite | 不变 |
| Python 工具 | uv、ruff、pytest | 新增 uv 管理依赖，Pi 上部署更简单 |
| 面板通信 | WebSocket，JSON 消息，按 schema 校验 | 新增 |
| 哼唱转谱 | Basic Pitch（Spotify，Apache-2.0）后接量化 | FretStudio 已有音频转 MIDI 的工作进程，可参考；在 Pi 上的速度要实测 |
| 打印 | python-escpos 驱动 58 毫米热敏打印机 | 新增 |
| 二维码 | 服务端 `qrcode` 生成，前端 `jsQR` 或 BarcodeDetector 识别 | 新增 |
| 节奏型 | 共用 JSON 数据，后端展开成吉他音符 | FretStudio 的节奏型写在前端 TypeScript 里，后端拿不到 |
| 模型调用 | 统一适配层，每类调用（和声候选、种子卡解析、写词、风格化、歌声合成、整曲渲染）一个接口，可换供应商；全部带超时并落回离线路径 | FretStudio 默认绑定 gpt-4o |

## 离线与联网

| 环节 | 联网 | 离线 |
| --- | --- | --- |
| 和声候选 | 模型候选，HRE 打分 | 进行库与规则候选，HRE 打分 |
| 种子卡解析 | 多模态模型 | 颜色统计、关键词、节拍检测 |
| 歌词 | 模型按音数写词 | 用户自己写 |
| 人声 | 歌声合成 | 用户自己录的一轨，或不出人声 |
| 乐器与环境声 | 本地采样 | 本地采样 |
| 卡片风格化 | 图像生成模型 | 本地滤镜 |
| 歌曲页 | 上传并生效 | 排队，联网后上传 |

## 共用接口（第 0 步，已完成）

| 文件 | 内容 |
| --- | --- |
| `shared/schema/song.schema.json` | 歌曲模型：时间用整数 tick（每四分音符 480），音高用 MIDI 编号；六轨、段落、和弦与指法、锁定、种子卡、卡片 |
| `shared/schema/panel-events.schema.json` | 面板 WebSocket 消息：面板只报原始动作（唱盘、旋钮、推子、按键），app 决定含义并回发灯光 |
| `docs/api.md` | HTTP 接口：歌曲只经服务器修改，每次修改返回整首歌；用 revision 防止冲突；需要联网但没网时返回 503 |
| `shared/data/rhythm-presets.json` | 从 FretStudio 导出的 30 个节奏型及难度级别，前后端共用 |
| `shared/schema/examples/` | 示例歌曲和示例消息（含应被拒绝的） |
| `shared/schema/tests/` | 校验 schema 本身有效、示例符合 schema、示例满足 schema 表达不了的规则 |

三个并行代理只按这些接口对接，不读彼此的实现。要改接口，先改这里并让测试通过，再通知其他代理。
