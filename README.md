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

第一阶段（milestone 1）完成：离线生成、HTTP API、iPad 网页、面板桥、固件草稿、屏幕模拟器、卡片渲染与打印都已实现，可以在没有网络、没有硬件的情况下跑通。运行全部测试：`./scripts/test-all.sh`。

还缺：固件未在真机上编译；真实 MIDI 读取和热敏打印机未在硬件上测；人声合成、歌词生成和分享上传属于 v2。

| 文档 | 内容 |
| --- | --- |
| [docs/design.md](docs/design.md) | 设计：场景、面板布局、控件、卡片、硬件、供电、分期 |
| [docs/architecture.md](docs/architecture.md) | 技术架构：模块划分、技术选型、和 FretStudio 的不同 |
| [docs/porting-from-fretstudio.md](docs/porting-from-fretstudio.md) | 从 FretStudio 移植哪些模块、不移植哪些 |
| [docs/model/index.html](docs/model/index.html) | 可交互的 3D 原型：控件能操作、能出声，下载后用浏览器打开 |
| [AGENTS.md](AGENTS.md) | 给开发代理的规则 |

## 目录

```
engine/          和声与编配核心（Python 库，从 FretStudio 移植）
server/          Raspberry Pi 上的后端：歌曲模型、生成、渲染、打印
app/             iPad 上的网页应用（React + TypeScript）
device/bridge/   面板事件桥：读控制板，经 WebSocket 发给 app
device/firmware/ 控制板固件
device/card/     卡片渲染与热敏打印（fretcase_card）
device/simulator/ 屏幕上的面板模拟器
shared/schema/   歌曲模型和面板事件的 JSON Schema，前后端共用
docs/            设计与架构文档
scripts/         运行全部测试等脚本
```

## 目标

UIST 2027 demo，或 TEI 2028。
