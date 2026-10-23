# 🐦 皖境飞鸟观测台 · WANBIRD OBSERVATORY

基于 AI 数媒技术的安徽珍稀鸟类科普互动网站，深色 HUD 风格。共三个模块：

- **识别**（首页）：上传鸟图 → 识别种类、置信度、中文简介与完整物种档案。
- **鸟类图鉴**：安徽及全国重点保护鸟类的百科目录（当前 **394 种**，含东方白鹳/朱鹮/勺嘴鹬/中华秋沙鸭等），支持搜索、按目筛选，点开查看详情。
- **鸟类短剧**：科普短剧播放频道（本地 MP4 / B 站视频）。
- **知识答题**：7 大考点速学卡（链接站外科普站点：百度百科 / iNaturalist / 懂鸟 / IUCN 等）+ 50 道珍禽知识题；题目对应这些站点的知识点，每题解析附「去学考点」外链。

后端调用「**懂鸟动物识别 API**」（HHOLOVE AI 开放平台）完成识别与百科查询，Flask 作为代理隐藏 API key、转发请求；图鉴与短剧数据为本地 JSON 静态配置。

## 功能

- 点选 / 拖拽上传图片，实时预览
- 识别鸟种 + 置信度进度条 + 中文简介
- **物种档案**：除简介外还展示
  - **分类阶元**：纲 → 目 → 科 → 属（中文名 + 拉丁名）
  - **IUCN 保护等级**（LC/NT/VU/EN/CR 分级配色徽章）
  - **栖息环境 / 地理分布 / 生活习性 / 外形特征 / 区别辨识 / 鸣叫特征 / 生长繁殖 / 保护现状**（有哪节显示哪节）
  - 英文名、俗名（别名）
- **Top-5 候选鸟种**（真实模式）
- **演示模式 / 真实模式**自动切换：
  - 未配置 API key → 返回演示数据（标注「演示数据」），方便调试界面，且不消耗免费额度
  - 配置了 API key → 真实调用懂鸟 API

## 安装与运行

### 1. 安装依赖

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

> 依赖：`flask`、`requests`、`python-dotenv`。见 [requirements.txt](requirements.txt)。

### 2. 启动（演示模式）

```bash
python app.py
```

浏览器打开 <http://127.0.0.1:5000>，上传任意图片即可看到演示结果（不会消耗真实额度）。

### 3. 切换为真实识别

去 [HHOLOVE AI 开放平台](https://ai.open.hhodata.com) 申请懂鸟 API key（新用户通常有免费图像识别额度）。

把 key 写进项目根目录的 `.env`（复制 [.env.example](.env.example)）**或**设置环境变量：

```bash
# Windows (CMD)
set DONGNIAO_API_KEY=你的key
# Windows (PowerShell)
$env:DONGNIAO_API_KEY="你的key"
# macOS / Linux
export DONGNIAO_API_KEY=你的key
```

重启 `python app.py`，即切换为真实识别。

> 端口可用环境变量 `PORT` 修改（默认 5000）。

## 识别流程（真实模式）

1. 前端上传图片 → `POST /classify`
2. Flask 调懂鸟「上传图片」接口，拿到 `resultid`
3. 轮询「获取识别结果」直到完成
4. 取最高置信度物种 → 调「获取百科资料」接口拿简介
5. 返回 `{ species, latin, confidence, description, source }`

接口详情见懂鸟 OpenAPI 规范：<https://ai.open.hhodata.com/doc.json>

## 项目结构

```
├── app.py                 # Flask 后端（识别代理 + 图鉴/短剧路由 + mock/real 切换）
├── data/
│   ├── birds.json         # 鸟类图鉴静态档案（394 种）
│   ├── dramas.json        # 短剧片源配置表
│   └── quiz.json          # 知识答题题库与科普资源
├── templates/
│   ├── base.html          # 公共布局（顶部导航 + 页脚）
│   ├── index.html         # 识别页
│   ├── guide.html         # 图鉴首页（搜索/筛选 + 卡片）
│   ├── bird.html          # 鸟种详情页
│   ├── drama.html         # 短剧频道页
│   └── quiz.html          # 知识答题页
├── static/
│   ├── css/site.css       # 共享深色 HUD 设计系统
│   ├── js/common.js       # 图片兜底等公共前端工具
│   ├── img/birds/*.svg    # 六种鸟的风格化剪影占位图
│   └── media/             # 短剧本地 MP4（自行放入）
├── requirements.txt       # Python 依赖
├── .env.example           # API key 配置示例
└── README.md
```

## 鸟类图鉴：更换照片

图鉴默认显示手绘剪影（`public/static/img/birds/<id>.svg`）。要换成真实照片，把照片命名为对应 id 放入同目录即可，前端自动优先加载 `.jpg`，无需改代码：

```
public/static/img/birds/oriental-stork.jpg        # 东方白鹳
public/static/img/birds/crested-ibis.jpg          # 朱鹮
public/static/img/birds/spoon-billed-sandpiper.jpg # 勺嘴鹬
public/static/img/birds/scaly-sided-merganser.jpg  # 中华秋沙鸭
public/static/img/birds/hooded-crane.jpg          # 白头鹤
public/static/img/birds/elliots-pheasant.jpg      # 白颈长尾雉
```

> 环境无法访问 Wikimedia 等海外图源，因此采用本地图 + 剪影兜底方案。新增/修改鸟种直接编辑 `data/birds.json`。

**自动配真实照片**：运行 `python download_bird_photos.py` 可为没有照片的鸟自动从 GBIF / iNaturalist 开放数据下载授权写真（压成 `public/static/img/birds/<id>.jpg`，摄影师与许可记录在 `public/static/img/birds/CREDITS.json`）。你已放了自己的照片（`<id>.png`）的鸟不会被覆盖。

每种鸟在 `data/birds.json` 里还有一个 `map` 字段（栖息地分布地图）：`ranges` 为范围多边形（越冬/繁殖/留鸟等，示意级）、`sites` 为关键保护区/观测点坐标，详情页用 Leaflet + 高德瓦片渲染（瓦片已实测可用；勿改 OSM）。想调整范围或点位，改这个字段即可。

详情页地图默认是一幅**完整世界地图**（中心 0°经线，整幅世界均可见），并叠加一层**真实观测记录**（青绿小点，可开关）：数据来自 GBIF 官网数据库（`public/static/data/occur/<id>.json`，CC BY 4.0，1980 年以来的真实坐标记录）。地图活动范围钳制在世界边界，只能在一个单幅世界里平移，不会无限左右滑动；「聚焦本种」按钮可飞速到该鸟的分布中心。想刷新/更新观测数据，联网运行 `python download_gbif_occurrences.py` 即可重新下载。

## 鸟类短剧：添加剧集

编辑 `data/dramas.json`，每条支持两种片源：

```json
{ "id": "ep-1", "title": "白头鹤的冬天", "cover": "/public/static/img/placeholder.svg",
  "age": "7-8", "duration": "03:12", "synopsis": "……",
  "type": "mp4", "src": "/public/static/media/ep-1.mp4", "bvid": null }
```
```json
{ "id": "ep-2", "title": "朱鹮归来", "cover": "/public/static/img/placeholder.svg",
  "age": "5-6", "duration": "02:45", "synopsis": "……",
  "type": "bilibili", "src": null, "bvid": "BV1xxxxxxxxx" }
```

- `type: "mp4"`：把视频文件放进 `public/static/media/`，`src` 填其路径。
- `type: "bilibili"`：`bvid` 填 B 站视频的 BV 号，页面用官方播放器嵌入。

## 部署为公开网站（Render 免费，约 10 分钟）

> 前提：一个 GitHub 账号、一个 Render 账号（可用 GitHub 登录）。`.gitignore` 已挡掉 `.env`，密钥不会进仓库。

**本地准备（我已准备好）**：项目里已有 `render.yaml`（Render 蓝本）、`requirements.txt` 含 gunicorn、`.gitignore`。你只需执行下面这几步。

**1) 建 GitHub 仓库**：在 github.com 新建一个空仓库（如 `wanbird-observatory`，不要勾选自动生成 README/.gitignore）。

**2) 本地初始化并推送**（在项目目录执行）：
```bash
git init
git config user.name "你的名字"
git config user.email "你的邮箱"
git branch -M main
git add -A
git commit -m "皖境飞鸟观测台：识别+图鉴+短剧多页网站"
git remote add origin https://github.com/你的用户名/wanbird-observatory.git
git push -u origin main
```

**3) Render 一键部署**：render.com → New → Blueprint → 选择刚推送的仓库 → Render 自动读取 `render.yaml` → 填写环境变量 `DONGNIAO_API_KEY`（你的懂鸟 key，只存在 Render 服务端）→ Apply。等几分钟，完成会得到一个 `https://xxx.onrender.com` 正式域名，即可发给任何人访问。

**4) 以后修改网站**：本地改 → `git commit -am "说明"` → `git push`，Render 自动重新部署（通常 1 分钟左右生效）。改图鉴数据、短剧片源、地图、样式全走这一条流程，没有数据库迁移问题。

**⚠️ 识别额度的提醒**：网站公开后，任何访客都能用「识别」功能，会消耗你的懂鸟 API 免费额度。如果不想被消耗，两个选择：上线前删掉 `.env` 里的 key 走演示模式（`/classify` 返回假数据但页面可看），或在 `app.py` 的 `classify()` 里加一个使用开关（如环境变量 `ALLOW_CLASSIFY=1` 时才走真实识别）。需要的话我可以帮你改。

## 提示

- 图片需 ≤ 2MB（懂鸟接口限制）。
- 当前仅识别鸟类（`class=B`）。懂鸟还支持兽(M)/两栖(A)/爬行(R)/鱼类(F)及**鸟鸣音频识别**，如需可继续扩展。
