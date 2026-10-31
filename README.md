# GreenMate · 植物养护助手

GreenMate 将环境读数、历史过程、天气预报、植物知识和模型预测组织成可回查的养护分析。界面保留每项证据的来源、时间、可用状态和判断边界。

## 启动

在项目目录执行：

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload --port 8100
```

也可使用 `./run.sh`。打开 [首页](http://127.0.0.1:8100/)；接口文档位于 `/docs`。

在环境变量或项目 `.env` 中配置：

```dotenv
GREENMATE_API_KEY=你的密钥
GREENMATE_BASE_URL=https://api.deepseek.com
GREENMATE_MODEL=deepseek-chat
WEATHER_LAT=39.9
WEATHER_LON=116.4
DB_PATH=greenmate.db
```

密钥不写入源码或日志。天气使用无需密钥的 Open-Meteo。向量检索使用本地 `all-MiniLM-L6-v2`，首次加载需下载模型；中文排序存在局限，加载失败时回退关键词检索。

## 页面

| 页面 | 地址 | 功能 |
| --- | --- | --- |
| 首页 | `/` | 数据驱动温室、当前读数与功能入口 |
| 环境 | `/environment` | 温湿光、模拟/真实天气切换、24小时历史 |
| 问答 | `/conversation` | 普通问答、Agent工具链与持久问答记忆 |
| 知识 | `/knowledge` | 植物条目、语义搜索与热加载 |
| 预测 | `/prediction` | 下一小时预测、模型版本与评估指标 |
| 分析 | `/analysis` | 分析档案、历史趋势对照、天气影响对照、多源证据分析 |

照片与温室场景仅作示意，不是作物实测证据。温室的光照强度、光色和雾气分别映射当前光照、温度与空气湿度；实际数值始终以接口读数为准。图片加载失败显示植物线稿；三维渲染不可用时保留温室SVG。减少动态效果设置会关闭自动旋转、叶片摆动、数字动画及视差。

## 数据来源与边界

- `SIMULATED`：模拟数据，不能当作真实环境测量。
- `REAL_WEATHER`：户外天气温湿度；保留的光照不代表天气实测，也不能替代室内传感器。
- `MODEL_OUTPUT`：模型预测证据，不能替代历史、天气、知识或实际观测。
- 植物知识是条件性参考，不保证适用于某株作物的具体阶段。

没有土壤湿度、作物阶段等证据时，不能仅凭空气湿度决定是否浇水。天气仅采用预报有效时间不早于分析锚点的点；获取时间与预报有效时间分开保存。外部预报不保证内部环境一定跟随。

SQLite保存当前状态、环境历史、问答历史和分析档案。`seed_history.py`可幂等生成336条、间隔30分钟的模拟历史，所有记录明确标注来源；重复执行不会刷新原有时间。分析对照只准备受管模拟场景，不覆盖真实观测。

## Agent与工具链

普通问答使用当前状态、对话记忆和检索知识。Agent自主选择工具，Python端串行执行，最多请求模型5轮：

| 工具 | 用途 |
| --- | --- |
| `get_current_environment` | 获取当前环境及原始时间戳 |
| `get_environment_history` | 查询历史，合法范围为0至168小时，不含0 |
| `get_weather_forecast` | 获取配置地点未来12小时预报 |
| `search_plant_knowledge` | 检索本地植物知识，保留引用 |
| `predict_next_attention` | 调用已保存模型，不现场训练 |

工具统一返回 `status/source/time/data/error`。`ok`表示查询正常完成，允许空结果；`unavailable`表示来源暂不可访问；`error`表示参数或执行错误。空结果是“查过但未命中”，与“未取得证据”不同。

展开问答页工具链，可查看实际执行的工具、参数、状态、耗时和结果。未执行的工具不会伪记为已执行；总结失败时仍保留真实工具记录。旧客户端的 `allow_write` 字段保留兼容，当前工具集不启用环境写操作。

LLM仅对502/503/504、超时与连接错误最多重试两次，间隔1秒、2秒；400/401等错误不重试。最终失败返回 `llm_error`，不得用提示文字冒充模型回答。

## 分析与回查

固定问题为：

> 分析当前番茄生长环境状态以及接下来值得关注的变化，并说明判断依据。

程序围绕同一时间锚点整理当前状态、最近3小时连续历史和已保存模型输出，可选加入天气与带引用的知识。先生成结构化判断，再由LLM解释；证据缺失或存在分歧时如实保留。稳定环境与持续升温的对照使用相同末点，以观察历史过程对判断的影响。

每次运行生成独立 `run_id`，在请求LLM前先保存证据快照。关闭页面或更新环境后，仍能按编号回查当时的输入、预测、判断和解释；回查不重新请求天气，也不重新计算模型。

主要接口：

| 接口 | 用途 |
| --- | --- |
| `GET/POST /api/state` | 读取/局部更新当前状态 |
| `POST /api/set-source` | 切换模拟数据或真实天气 |
| `GET /api/environment/history` | 查询环境历史 |
| `POST /api/ask`、`POST /api/agent` | 普通问答与工具问答 |
| `GET /api/history` | 最近问答记录 |
| `GET /api/knowledge`、`GET /api/knowledge/search` | 知识列表与搜索 |
| `POST /api/knowledge/reload` | 重载知识和索引 |
| `GET /api/ml/dataset/summary`、`GET /api/ml/metrics` | 数据集与评估摘要 |
| `GET /api/ml/predict` | 已保存模型的最新窗口推理 |
| `POST /api/analyze` | 完整分析，可选天气与知识 |
| `GET /api/analyze`、`GET /api/analyze/{run_id}` | 最近档案与按编号回查 |
| `POST /api/analyze/scenario` | 准备模拟场景并分析 |
| `GET /api/analyze/compare` | 对比两个已归档结果 |

错误统一包含 `error.code/message/hint`。网络不可用时保留已有状态和证据，不编造天气、预测或回答。

## 模型与文件结构

模型文件为 `models/attention_v1.joblib`，manifest记录特征顺序、窗口配置、训练时间和评估摘要。推理校验特征顺序，不现场训练，不把预测写回原始采样表。

输入为6个连续半小时点，使用8个当前窗口特征，预测未来2个点。数据按时间切分，跨边界窗口丢弃；标准化只在训练集拟合。标签来源为 `RULE_v1`：未来平均温度≥32°C或≤10°C、湿度≤35%或≥85%、光照≥20000或≤800 lux，任一满足记WATCH，否则NORMAL。这是透明规则标签，不是植物病害诊断，模型概率未经校准。

六个HTML分别承载各页内容；`static/app.css`和`static/app.js`提供共用样式与请求工具，各页脚本仅操作本页DOM。`static/scene.js`只在首页加载，Three.js由本地vendor提供。`assets/img/`中的六张摄影感图片由AI生成，仅作装饰；生成提示词保存在 `assets/img/PROMPTS.json`。

## 验证

```sh
HF_HUB_OFFLINE=1 .venv/bin/python -m unittest discover -q
```

页面验证说明位于 `verification/PAGES.md`，包含桌面/移动布局、原功能、来源标记、缺图、三维降级和断网检查。界面测试中的天气/LLM夹具只证明页面行为，不代表真实上游可用；独立真实天气联调记录与之分开保存。已记录的旧测试结果不等于当前上游服务的可用性保证。

实际操作顺序见 [DEMO.md](DEMO.md)。
