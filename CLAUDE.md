# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

**本项目已升级为多页面网站「皖境飞鸟观测台」，共三个模块：**

1. **识别（首页）**：上传鸟类图片，识别鸟种、置信度并返回中文简介 + 完整物种档案。后端调用「懂鸟动物识别 API」（HHOLOVE AI 开放平台），Flask 作代理隐藏 API key。

2. **鸟类图鉴**：安徽及全国重点保护鸟类的百科目录，当前 **394 种**全部具备**自动生成版六节档案 + 栖息地数据**（`enrich_birds_from_gbif.py`：GBIF 英文名 + 观测点下载到 `public/static/data/occur/<id>.json` + 目级科学模板正文 + 观测点凸包生成「观测分布区」范围；广布/跨洲种因跨度过大只显示观测点，地图角标"仅真实观测点"）。IUCN 等级与一级/二级保护级别、精写正文仍未填（自动生成版为模板通性描述，正文已标注自动生成）。

3. **鸟类短剧**：科普短剧播放频道，片源配置在 `data/dramas.json`（本地 MP4 / B 站 bvid）。
4. **知识答题**：`/quiz` 页面，7 大考点速学卡（链接站外科普站点：百度百科词条 / iNaturalist 物种页 / 懂鸟 / IUCN / eBird）+ 50 道题库（`data/quiz.json`，随机抽 10 题、判分带解析、题目带考点标签、每题解析附「去学考点」外链）。

> 图鉴与短剧沿用设计文档《皖境飞鸟观测台》的深色 HUD 风格与科普分级（0-4 / 5-6 / 7-8）思路。设计文档的完整技术方案见下文「皖境飞鸟观测台（设计文档）」章节。

## 皖境飞鸟观测台（设计文档）

设计文档文件：`皖境飞鸟观测台——基于AI数媒技术的安徽珍稀鸟类科普互动网页.pptx.pdf`（17 页 PPT）。

⚠️ **该 PDF 带 owner 密码**，Read 工具无法直接读取。需用命令行提取文本：
```bash
pdftotext -upw "" "皖境飞鸟观测台——基于AI数媒技术的安徽珍稀鸟类科普互动网页.pptx.pdf" -   # 输出到终端
pdftotext -upw "" -layout "皖境飞鸟观测台——基于AI数媒技术的安徽珍稀鸟类科普互动网页.pptx.pdf" out.txt
```
注意：PPT 转 PDF 后**中文字符大量丢失**（多数字体被转成图片或乱码），能读到的是英文标签、数字和技术名词——转为图片的页面需看图。

原型网站（豆包 apps）：<https://4m41xjmjk5m16.doubaoapps.com/app/app_17epdax6ns6>

从 PDF 可提取的设计要点：
- **技术栈**：纯 HTML/CSS/JS，Hash 单页，约 5 个分区。
- **设计系统**：深色 HUD（平视显示器）风格，配色 `#0a1f1f`（深底）+ `#e8a838`（金色主色）+ `#143c3c`（副色）；CSS Keyframes 动画 + IntersectionObserver 滚动触发。
- **AI 识别（FGVC 细粒度分类）**：STEP1 YOLOv8/v12 检测 → STEP2 EfficientNet / ResNet50 分类 → STEP3 Top-5 + 置信度。
- **识别方案对比**：懂鸟 Aboutbirds API（11,000+ 种，Top-1 85% / Top-5 96%，本仓库 flask 已接）；自部署 ONNX Runtime + MobileNetV2；备选 iNaturalist、Merlin（8,000+ 种）。
- **声音识别**：WAV/MP3/AAC/OGG，Web Audio API（AudioContext / AnalyserNode）+ Canvas，RMS 分频段（<1500Hz / 1500-3500Hz / >3500Hz）→ Top-2 匹配。
- **USB 相机直连**：WebUSB + PTP（Chrome/Edge）；备选 Python gphoto2（Linux/Mac/WSL）或 digiCamControl（Windows）经 WebSocket。
- **科普内容分级**：按年龄段（7-8 / 5-6 / 0-4）区分介绍深度。

> 现状：该项目的实现尚未开始；本仓库已实现的「鸟类识别网页」可作为其识别能力的起点（已接懂鸟 API）。

## 常用命令

```bash
# 安装依赖
pip install flask requests python-dotenv

# 启动（开发服务器，监听 http://127.0.0.1:5000）
python app.py
```

- 无测试套件、无 lint 配置、无构建步骤（前端是 Flask 模板渲染的单文件）。
- 端口：默认 5000，可用环境变量 `PORT` 修改。**若 5000 被残留进程占用会自动改用下一个空闲端口**并打印实际地址。

## 运行模式（关键）

模式由环境变量 `DONGNIAO_API_KEY` 是否设置决定，`real_mode()`（app.py:42）每次请求时判定：

- **未设置 key** → `演示(mock)` 模式：`/classify` 返回预置假数据（`source: "mock"`），不消耗免费额度，用于调试 UI。
- **已设置 key** → 真实识别：走懂鸟 API 完整流程，`source: "real"`。

key 通过项目根目录 `.env`（由 `python-dotenv` 在 app.py:22-26 加载）或系统环境变量提供。**修改 `.env` 后必须重启进程**——`load_dotenv()` 只在启动时执行一次。

⚠️ Windows 开发注意事项：反复用 debug 启动会堆积残留 Flask 进程占用 5000 端口，导致新进程连到旧实例、加载旧的 key 配置（表现为"配了 key 仍返回演示数据"）。app.py:249 已设 `use_reloader=False` 缓解；彻底清残留用 `taskkill /F /IM python.exe`。

## 架构

```
app.py                 # Flask 后端，单文件（识别 + 图鉴/短剧路由）
templates/
  base.html            # 公共布局：顶部导航（识别/图鉴/短剧）+ 页脚
  index.html           # 识别页（继承 base，页面内 CSS/JS 自持）
  guide.html           # 图鉴首页（搜索/筛选 + 卡片，JS 渲染）
  bird.html            # 鸟种详情页
  drama.html           # 短剧频道页（播放器 + 剧集列表）
  quiz.html            # 知识答题页（纯前端抽题判分）
static/
  css/site.css         # 共享深色 HUD 设计系统（token/按钮/徽章/分节卡等）
  js/common.js         # 图片兜底等公共前端工具
  js/birdmap.js        # 栖息地地图组件（Leaflet + 高德瓦片 + 范围/点位/图例）
  lib/leaflet/         # 本地化 Leaflet 1.9.4（js/css/images）
  img/birds/*.svg      # 六种鸟剪影占位图；放同名 .jpg/.png 自动替换
  media/               # 短剧本地 MP4
data/
  birds.json           # 图鉴静态档案（含每个物种的 map 字段）
  dramas.json          # 短剧片源配置
  quiz.json            # 知识答题题库与科普资源
.env / .env.example    # API key 配置（.env 不入库，仅在本地）
README.md              # 安装、运行、配置说明
```

- `app.py` 启动时用 `_load_json()` 读取 `data/*.json`（标准库 json，无新依赖）。
- 路由：`/`（识别）、`/guide`、`/guide/<bird_id>`、`/drama`、`/quiz`、`/classify`、`/mode`。
- 图鉴图片兜底：`<id>.jpg` → `<id>.png` → `<id>.svg`（剪影）→ `placeholder.svg`，见 `public/static/js/common.js` 的 `birdImg()`。
- 栖息地地图：`birds.json` 每只鸟的 `map` 字段（`ranges` 范围多边形 + `sites` 关键地点，坐标为经纬度），由 `public/static/js/birdmap.js` 用 Leaflet 渲染，瓦片用高德 `webrd0*.is.autonavi.com`（本机实测可用；**OSM 瓦片在本网络被屏蔽，勿换**）。深色化通过只对瓦片做 CSS `filter: invert(...)` 实现，不动矢量图层。动态效果：点位呼吸脉冲光圈（`site-ring`）、范围轮廓虚线流动（`dashFlow`）+ 专属色光晕 + 加载渐入；`staging` 类停歇地渲染为发光流动折线；`prefers-reduced-motion: reduce` 时自动停用动画。
- 真实观测点图层：`public/static/data/occur/<id>.json` 存每只鸟的 GBIF 真实坐标（[经, 纬] 数组，GBIF.org · CC BY 4.0，1980 年以来），页面开关控制显隐。用 `python download_gbif_occurrences.py` 可重新拉取刷新。地图默认是一幅完整世界地图（中心 0°经线、`minZoom=2` 整幅世界可见），`maxBounds` 钳制在世界边界——只能在一个单幅世界里平移，不能无限左右滑动进空白；「聚焦本种」按钮用 `setView(物种中心, 7)` 飞到分布中心（不用 fitBounds，因为在世界 maxBounds 下高缩放时中心锁消失）。
- 自动配写真：`python download_bird_photos.py [鸟名]` 从 GBIF 检索 iNaturalist 开放数据授权照片，压存 `public/static/img/birds/<id>.jpg`（摄影师/许可写入 `CREDITS.json`）；已有用户照片（`<id>.png`）的鸟跳过不覆盖。
- 图鉴改进（2026-10-19）：`improve_from_inaturalist.py` 用 iNaturalist **CC 授权精选图**替换图片（332 种）、用 GBIF **国家分布统计**重写「地理分布」（379 种）、补英文名；**只用 CC 图，ARR/版权保留一律不取**。详情页新增「DATA SOURCES 数据来源」区块（GBIF / 名录 / iNaturalist 摄影师+许可+原页 / 自动生成说明），路由通过 `PHOTO_CREDITS` 传入图片署名。已纠正「栗鹀」→「栗斑腹鹀」（一级）。`birds.json` 与 `CREDITS.json` 都在启动时载入，改动后需重启服务。
- 环境无法访问 Wikimedia 等海外图源，故图鉴用本地图 + 剪影方案。
- 部署：当前使用 **Vercel**（免费 Hobby，无需银行卡）：`api/index.py` 导入根目录的 `app`，`vercel.json` 用 rewrites 把全部请求转到 `/api/index`，`includeFiles` 必须是**字符串**（写成 `"**"`），函数 `maxDuration: 60`（识别轮询需要）。Render 需要绑定银行卡（已弃用）；国内服务器需 ICP 备案，备案省份须与身份证省份一致（重庆身份证→需重庆地域服务器，阿里云无重庆地域，腾讯云仅 CVM 有）。域名 `anhuibird.cn` 解析到 Vercel（海外）**无需备案**。

### 后端核心流程（真实模式，app.py:157-211）

`POST /classify` 接收前端上传的图片（`multipart` 字段 `image`，≤2MB），然后：

1. `upload_image()` — 调懂鸟「上传图片」接口，拿 `resultid`
2. `poll_result()` — 轮询「获取识别结果」直到完成，解析候选列表
3. `fetch_encyclopedia()` — 取最高置信度物种，调「获取百科资料」拿简介
4. 返回 JSON 给前端

### 懂鸟 API 协议要点

- Base URL：`https://ai.open.hhodata.com/api/v2`；单一接口 `POST /dongniao`，靠不同表单字段区分 5 种操作（上传图片 / 上传鸟鸣 / 获取结果 / 获取百科 / 查配额）。
- 鉴权：header `api_key`（app.py:52）。
- 响应恒为 HTTP 200，体是 `[code, payload]` 数组：
  - `[1000, "HH-B_..."]` = 任务已受理（字符串即 `resultid`）
  - `[1000, [[{box, list:[["置信度%","中文名|英文|学名","animalid","类别"]]}]]]` = 识别完成
  - `[1001]` = 处理中（需轮询）；`[1010,"No animals"]` / `[1008,"No boxes"]` = 未识别到动物（两者都按无结果返回友好提示，`poll_result` 已处理）
- 图片限制 ≤2MB；识别类别 `class=B`（鸟），懂鸟还支持兽 M/两栖 A/爬行 R/鱼类 F 及鸟鸣音频。

### 值得注意的实现点

- `_flatten()`（app.py:119）递归展开嵌套 payload 提取含 `box` 的字典。
- `_extract_description()`（app.py:130）对百科 payload 做宽松兜底解析（字段名不确定，按候选键取文本），失败返回兜底文案不阻断主流程。
- 置信度：懂鸟返回百分比，服务端换算为 0-1 小数返回前端。
- 前端根据响应 `source` 字段决定是否显示「演示数据」标签（index.html 中 `#sourceTag`）。

## 外部资源

- 懂鸟 API 文档：<https://ai.open.hhodata.com/doc/>；OpenAPI 规范：<https://ai.open.hhodata.com/doc.json>
- 懂鸟 API key 申请：HHOLOVE AI 开放平台 <https://ai.open.hhodata.com>
