# FretCase

A vintage suitcase that lets someone with no musical training make a song of their own while travelling. They hum, record a sound, take a photo or write a line; FretCase proposes a multi-track arrangement; they reshape it with physical controls; and the song is printed as a card that plays back from a QR code.

FretCase grows out of [FretStudio](https://github.com/Mr-Sushi/FretStudio) and reuses part of its harmony and arrangement engine. Everything else is chosen fresh for this device.

---

## 是什么

一只棕色复古皮箱：箱盖里是 iPad，箱底是实体控件。用户用哼唱、环境声、照片或一段文字做起点，几分钟内做出一首歌，再印成一张卡片带走：正面是照片转成的水墨、漫画或写意画，背面是二维码，扫码就能听。

- 不要求乐理：控件叫"明暗、简繁、疏密"，背后对应调式、和弦词汇和节奏密度。
- 生成拆成几步，每一步都有实体控件，用户可以逐段、逐音轨地改。
- 联网优先（手机热点），离线时整条流程仍能跑。

## 现状

设计阶段，代码尚未开始。

| 文档 | 内容 |
| --- | --- |
| [docs/design.md](docs/design.md) | 设计：场景、面板布局、控件、卡片、硬件、供电、分期 |
| [docs/architecture.md](docs/architecture.md) | 技术架构：模块划分、技术选型、和 FretStudio 的不同 |
| [docs/porting-from-fretstudio.md](docs/porting-from-fretstudio.md) | 从 FretStudio 移植哪些模块、不移植哪些 |
| [docs/model/index.html](docs/model/index.html) | 3D 结构模型，下载后用浏览器打开 |
| [AGENTS.md](AGENTS.md) | 给开发代理的规则 |

## 目录

```
engine/          和声与编配核心（Python 库，从 FretStudio 移植）
server/          Raspberry Pi 上的后端：歌曲模型、生成、渲染、打印
app/             iPad 上的网页应用（React + TypeScript）
device/bridge/   面板事件桥：读控制板，经 WebSocket 发给 app
device/firmware/ 控制板固件
shared/schema/   歌曲模型和面板事件的 JSON Schema，前后端共用
docs/            设计与架构文档
```

## 目标

UIST 2027 demo，或 TEI 2028。
