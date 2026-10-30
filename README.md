# GreenMate：B05 教材工具契约

B05 建立四个只取证工具，B06 第3步增加第五个模型预测工具（见文末）。模型自主决定是否调用、调用哪些工具及调用顺序；Python 端串行执行，最多请求模型 5 轮。未接入 MCP 或多智能体框架。

## 启动

```bash
cd "/Users/xiaoyi/Documents/ChatGPT/B01-B08软件智能基础与竞赛原型实践指南/greenmate"
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python seed_history.py
.venv/bin/uvicorn main:app --reload --port 8100
```

打开 [首页](http://127.0.0.1:8100/) 或 [接口文档](http://127.0.0.1:8100/docs)。在启动前通过环境变量或项目 `.env` 配置 `GREENMATE_API_KEY`。`GREENMATE_BASE_URL`、`GREENMATE_MODEL` 可覆盖模型平台默认配置；天气不需要 key，使用 `.env` 的 `WEATHER_LAT=39.9`、`WEATHER_LON=116.4`。

向量模型仍为本地 `all-MiniLM-L6-v2`，首次使用需要下载到 `.models/`；之后可离线加载。知识向量存于 `knowledge/index.json`，不存入 SQLite。

## 历史样本

`environment_samples` 与 `current_state` 分表存储。`add_sample(state)` 显式增加一个样本，`get_samples(hours=24)` 读取当前时间之前指定窗口的记录，按 UTC `timestamp` 升序返回。

`seed_history.py` 在一次事务中生成 7×48=336 条记录，相邻间隔 30 分钟。温度、湿度和光照按北京时间昼夜变化，并叠加固定随机种子的噪声。所有记录都标记 `source_type=SIMULATED`、`sim_scenario=seed_demo`，不能作为真实环境测量。

重复运行脚本检测到已有 `seed_demo` 后跳过，不重复插入，也不滚动刷新原有演示时间，不修改当前状态。脚本没有定时轮询；本轮也不会把每次读取伪装成新样本。需要追加其他样本时显式调用 `add_sample`。

## 四个工具

| 工具 | 参数 | 成功数据 | 典型失败 |
|---|---|---|---|
| `get_current_environment` | 无 | `data` 为当前温度、空气湿度、光照、来源、原状态时间戳 | 状态未加载：`unavailable` |
| `get_environment_history` | `hours=24`，数值，`0<hours<=168` | `data.hours/items/count`；保留每条样本的来源及场景 | 非法 hours：`error`；数据库不可用：`unavailable` |
| `get_weather_forecast` | `location`，如 `北京` | 下一个 UTC 整点开始连续 12 小时的温度、空气湿度，含单位与时间；不覆盖当前状态 | 5 秒连接/读取超时或服务失败：`unavailable`；未配置地点：`error` |
| `search_plant_knowledge` | 非空 `query` | `data.query/items` | 无匹配：仍为 `ok` 且 `items=[]`；非法 query：`error` |

预报沿用单个配置地点，支持名称 `北京`、`Beijing`、`配置地点`、`当前地点`，不提供多城市切换。预报使用 [Open-Meteo Forecast API](https://open-meteo.com/en/docs) 的 `hourly`、`start_hour`、`end_hour` 参数；时间为 UTC，不能当作当前室内传感器读数。

植物工具使用 `search_plant_knowledge`，未沿用旧案例的 `search_tomato_knowledge`。向量结果加相似度门槛 `rag.MIN_SIMILARITY=0.45`，避免所有查询都硬返回两条。该分数不是概率；英文模型的中文排序限制仍存在，见 `knowledge/README.md`。

统一返回外壳：

```json
{"status":"ok","source":"SIMULATED","time":"2026-10-21T00:00:00+00:00","data":{},"error":null}
```

- `ok`：请求合法且证据查询正常完成，数据可以为空。
- `unavailable`：证据源暂不可访问，如天气超时或数据库不可用；不能据此编造预报或历史。
- `error`：参数或工具执行不合法，应检查请求。

空结果表示“查过，但没有匹配证据”，与“没能完成查询”不同。Agent 会在最终回答中补充对应证据缺失说明，包括正常的空结果。

兼容说明：本轮按教材替换了旧 Agent 工具集，`set_environment` 不再暴露或执行。旧客户端传入的 `allow_write` 仍可被接受，但不会增加写权限；首页已去掉该复选框。B03 手动切换来源等独立接口和 `/api/ask` 对照组保留。

## 观察实际工具链

首页的 **Agent 对话** 中输入，例如：

> 查看当前环境和最近24小时历史，获取北京未来12小时预报，并检索植物缺水相关知识。逐项说明来源和缺失证据。

回答下展开“本次工具调用链”，查看每项 `sequence/tool/arguments/status/result/elapsed_ms`。`sequence` 每次请求从 1 递增；`elapsed_ms` 是实际工具执行（含工作线程排队）的耗时，不是模型请求耗时。完整结果包含统一外壳，可继续展开。

也可直接调用：

```bash
curl http://127.0.0.1:8100/api/agent \
  -H 'Content-Type: application/json' \
  -d '{"question":"查看当前环境和最近24小时历史，并说明是否为模拟样本。"}'
```

实际执行后终端输出一行 `[agent.tool] {JSON}`，其中包括完整结果；模型没有调用工具时不会伪造日志。可选保存服务日志：

```bash
mkdir -p verification
.venv/bin/uvicorn main:app --port 8100 2>&1 | tee verification/server.log
```

上述命令应在停止其他 8100 服务后运行。API 不写死工具调用顺序；用户问题与模型的决策决定本次调用链。

## 复现三类失败验证

```bash
HF_HUB_OFFLINE=1 GREENMATE_FAILURE_EVIDENCE=verification/b05_failures.jsonl \
  .venv/bin/python -m unittest -v test_agent_failures
```

这组测试使用临时 SQLite，执行真实注册的 Python 工具，并检查 `[agent.tool]` 日志和最终回答。为保证非法 `hours=-1` 不被模型自动修正，LLM HTTP 回复由测试驱动；这不等于真实模型自主决策验收。

1. `get_environment_history(hours=-1)`：返回 `error`，最终回答说明该次历史证据缺失。
2. 用 `requests.Timeout` 故障注入调用 `get_weather_forecast("北京")`：返回 `unavailable`，最终回答说明未来12小时预报缺失。没有降低超时时间或等待真实断网。
3. `search_plant_knowledge("不存在的内容xyz")`：调用真实向量检索（模型不可用则原有关键词回退），返回 `ok`、`data.items=[]`、`error=null`；最终回答说明没有匹配的本地知识。

证据 JSONL 为追加写入，包含测试模式、真实工具记录、耗时、最终回答和捕获到的日志。真实模型自主决策的单独验收结果见 `verification/b05_live.json`、`verification/b05_live.log`（生成后）。不要把测试驱动的模型回复当成真实模型调用证明。

可选执行真实模型验收（使用已配置的平台，可能消耗模型额度）：

```bash
.venv/bin/python verify_b05_live.py
```

该脚本只在临时数据库中生成本轮定义的模拟历史与默认模拟当前状态，天气地点固定为公开的北京示例坐标。不读取或发送项目数据库中的现有状态、历史；保存的报告同样只包含合成样本、公开植物资料和天气预报。调用哪些工具、顺序如何由真实模型决定。

### 本轮实际验收记录（2026-10-21）

- 正式数据库已写入 336 条 `seed_demo`，再次运行新增 0 条；未修改当前状态。
- 全量 62 项单元测试通过；三类失败证据见 `verification/b05_failures.jsonl`。
- 两次真实模型验收均由模型自主发起全部四个工具调用，完整结果和可观察日志保存在 `verification/b05_live.json`、`verification/b05_live.log`；第一次记录保存在 `b05_live_first_attempt.*`。
- 联网限制：天气请求实际失败并返回 `unavailable`；取得工具结果后的第二轮模型连接也失败，报告为 `model_error`。已保留执行记录与缺失证据说明，不能将其视为完整联网最终回答通过。三类失败的最终回答断言来自上述可复现的故障注入测试。

全量回归测试：

```bash
HF_HUB_OFFLINE=1 .venv/bin/python -m unittest discover -v
```

测试不会覆盖正式当前状态或往正式数据库添加测试记录；只有显式执行 `seed_history.py` 会向项目数据库追加演示样本。

## B06 第1步：数据集构造（不训练模型）

```bash
.venv/bin/python ml_dataset.py
.venv/bin/python ml_dataset.py --window-size 4 --horizon 2
# 验收后可恢复教材默认配置
.venv/bin/python ml_dataset.py --window-size 6 --horizon 2
```

命令读取全部 `environment_samples`，打印摘要并保存项目根目录的 `dataset_config.json`。配置记录窗口大小、预测跨度、30分钟间隔、8项特征、标签规则和切分时间。`GET /api/ml/dataset/summary` 使用最近生成的窗口配置重新读取数据库，返回相同结构的摘要；GET 不写文件。未生成配置时默认使用6/2。无需新增依赖或配置 API key。

以最早原始时间戳为起点，前5天 `[start,start+5天)` 是训练区间，后2天 `[start+5天,start+7天)` 是测试区间，之后的记录不进入本轮数据集。先切分原始记录，再分别滑动构造窗口：默认6个输入点、紧接着2个未来点，每次前移1点。整个8点序列必须每相邻点严格相隔30分钟；缺点、重复时间、异常间隔、缺失或非有限数值的窗口直接丢弃，不插值。只有 `SIMULATED` 记录能进入窗口，天气记录不会混入。训练和测试窗口所用的原始记录（含未来标签点）互不重叠。

`ml_dataset.load_samples()` 返回原始记录；`build_windows(window_size=6,horizon=2)` 返回样本列表，`split` 标明 train/test。样本包含稳定的 `sample_id`、输入起止 `window_start/window_end`、未来起止 `future_start/future_end`、`input_sample_ids`、原始 `input_timestamps`、`future_sample_ids`、`features`、`label` 和 `label_source`。可直接按ID在原表反查；元数据均不属于特征。

8项特征严格取自输入窗口：

| 特征 | 定义 |
|---|---|
| temp_current / hum_current / light_current | 输入窗口最后一点的温度 / 湿度 / 光照 |
| temp_mean / hum_mean | 输入窗口温度 / 湿度均值 |
| temp_delta / hum_delta / light_delta | 输入窗口最后一点减第一点 |

不使用未来原始值、`sim_scenario`、`label_source`、样本ID、来源或时间戳作为特征；不做标准化、不训练模型。

透明标签 `next_window_attention` 的来源为 `RULE_v1`：先分别计算未来窗口温度、湿度、光照均值，满足任意一项即 `WATCH`，否则 `NORMAL`：温度 ≥32°C 或 ≤10°C；湿度 ≤35% 或 ≥85%；光照 ≥20000 lux 或 ≤800 lux。边界值包含在内。这是教学规则标签，夜间低光也会按规则标为 WATCH，不能把该标签解释为真实植物病害诊断。

当前336条数据的实测结果：

| 输入点数 / 未来点数 | 训练样本 | 测试样本 |
|---|---:|---:|
| 6 / 2 | 233（NORMAL 118、WATCH 115） | 89（NORMAL 46、WATCH 43） |
| 4 / 2 | 235（NORMAL 118、WATCH 117） | 91（NORMAL 46、WATCH 45） |

默认切分时间为 `2026-10-19T09:30:00+00:00`。训练样本涵盖的原始时间范围截至 `2026-10-19T09:00:00+00:00`，测试从切分时间开始。具体摘要、6点回溯示例和两种窗口大小的实测对照见 `verification/b06_dataset.json`。这些计数只对应本轮已有的336条记录。

必须先按时间划分数据，才能模拟用过去训练、预测之后数据的过程；随机切分相邻滑动窗口会共享大量原始点，使测试结果虚高。跨边界窗口也要丢弃：否则训练输入或标签可能读到测试时段，或两侧共享同一批观测。未来值只能用于生成标签，不能进入输入特征；后续训练及标准化也应只拟合训练集。

```bash
.venv/bin/python -m unittest -v test_ml_dataset
```

测试覆盖时间隔离、6点原始时间戳回溯、4点窗口计数、缺口/重复点/天气/缺值剔除，以及修改未来值只改变标签而不改变特征。

## B06 第2步：训练与评估

```bash
.venv/bin/python ml_train.py
```

使用最近生成的 `dataset_config.json` 中的窗口配置，运行时先打印训练/测试类别分布，再打印完整指标和错误分析，保存 `ml_metrics.json`，不覆盖数据集配置。第2步原先只保存指标，第3步已扩展为同时保存模型和 scaler（见下节）；`GET /api/ml/metrics` 只读指标 JSON，不触发训练。尚未运行时返回404及运行提示；现有服务需重启或启用 reload 加载新路由。

依赖中已显式加入 `scikit-learn`，当前环境已安装。特征按照 `FEATURE_NAMES` 的固定8列顺序组装，WATCH=1、NORMAL=0。Precision/Recall/F1 都针对 WATCH 正类计算；无正类预测时 Precision 按 `zero_division=0` 记为0。混淆矩阵行为真实类别、列为预测类别，固定类别顺序 NORMAL、WATCH，即 `[[TN,FP],[FN,TP]]`。

训练阶段只构建 Train 数组：`DummyClassifier(strategy="most_frequent")` 从 Train 决定多数类；`StandardScaler.fit_transform(X_train)` 后，`LogisticRegression(max_iter=1000, random_state=42)` 仅拟合标准化后的 Train。之后才构建 Test 数组，调用同一个 scaler 的 `transform(X_test)`。决策阈值固定0.5，恰好相等时为 NORMAL。没有根据测试结果调参、调整阈值、搜索超参或交叉验证。

这一处理与 [scikit-learn 防止数据泄漏指南](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage) 一致。JSON 中 `training_audit` 记录 scaler 拟合样本数和均值，测试也实际拦截 fit 调用检查其只收到 Train。

本轮固定6/2配置，Train 233条（NORMAL 118、WATCH 115），Test 89条（NORMAL 46、WATCH 43）。多数类基线始终预测 NORMAL。实测指标如下（未四舍五入的数值保存在 JSON）：

| 基线 | 数据集 | Accuracy | Precision | Recall | F1 | TN / FP / FN / TP |
|---|---|---:|---:|---:|---:|---|
| 多数类 | train | 0.5064 | 0.0000 | 0.0000 | 0.0000 | 118 / 0 / 115 / 0 |
| 多数类 | test | 0.5169 | 0.0000 | 0.0000 | 0.0000 | 46 / 0 / 43 / 0 |
| 逻辑回归 | train | 0.9828 | 0.9664 | 1.0000 | 0.9829 | 114 / 4 / 0 / 115 |
| 逻辑回归 | test | 0.9775 | 0.9556 | 1.0000 | 0.9773 | 44 / 2 / 0 / 43 |

测试集WATCH Recall：多数类基线=0.0000，逻辑回归=1.0000；改善（差值+1.0000）。

### 测试集错误分析

第一个错分为 FP（假阳性）：`2026-10-19T19:00:00+00:00` 至 `2026-10-19T21:30:00+00:00`，真实 NORMAL，预测 WATCH，P(WATCH)=0.617325。原始8项特征：

```json
{
  "temp_current": 21.62,
  "temp_mean": 20.881666666666668,
  "temp_delta": 0.9800000000000004,
  "hum_current": 72.75,
  "hum_mean": 74.23166666666667,
  "hum_delta": -3.530000000000001,
  "light_current": 0.0,
  "light_delta": 0.0
}
```

假阳性：输入当前光照为0.00 lux、光照delta为0.00 lux；事后回查未来均值为温度22.54°C、湿度69.31%、光照1395.09 lux，未来三项均未触发RULE_v1，但模型WATCH概率高于0.5，产生误报。

这是对输入与事后标签证据的描述，不是模型内部因果解释。脚本最多打印3个实际错分；若没有错分，则选取概率最接近0.5的边界样本。错误分析中的未来均值只用于事后解释，未参与特征、标准化或训练。

Recall = TP/(TP+FN)，衡量真正需要提醒的 WATCH 中有多少被发现。养护提醒里漏报更值得关注；Accuracy 可能被 NORMAL 占比掩盖，本次多数类基线就有51.69%的测试 Accuracy，却漏掉全部43个 WATCH。Precision 仍需一起看，以衡量误报：逻辑回归本次产生2个误报。

多数类基线提供“不利用特征、只猜训练集最常见类别”的参照，判断模型是否比朴素猜测多学到了信息。当前高指标仅对应这7天合成数据及 RULE_v1 标签，不能解释为对真实养护风险的已验证能力；Train 指标是拟合诊断，Test 指标才是本轮时间留出的评估。

```bash
.venv/bin/python -m unittest -v test_ml_train
```

测试检查训练专用拟合、固定特征顺序、正类与混淆矩阵口径、指标文件/API一致性，以及无错分时的边界样本路径。

## B06 第3步：模型持久化与推理

本轮已显式运行一次训练并保存以下文件，之后启动服务无需训练：

- `models/attention_v1.joblib`：包含已训练逻辑回归、仅在Train拟合的scaler、固定特征顺序、完整窗口配置、标签映射、模型版本。
- `models/attention_v1_manifest.json`：记录版本、训练时间、特征顺序、6点输入/2点未来配置、scaler说明、标签映射、训练时间范围、训练/测试指标和模型文件SHA-256。

```bash
# 已有模型时只需启动服务；如8100已有旧进程，请先停止旧服务
.venv/bin/uvicorn main:app --reload --port 8100
curl http://127.0.0.1:8100/api/ml/predict
```

仅在明确需要重新生成本地v1文件时手动运行 `.venv/bin/python ml_train.py`，会覆盖同名v1；启动、GET推理及Agent均不会调用训练。没有自动重训练、AB版本或向 `environment_samples` 写入预测结果。`joblib` 已显式列入依赖，环境中原本随 sklearn 安装。

`ml_infer.load_model()` 每次读取本地文件并严格比较 manifest 的特征列表与 `ml_dataset.FEATURE_NAMES`，包含顺序；再校验模型包的同一列表、窗口配置、标签映射、拟合状态、维数和文件摘要。特征顺序不符立即抛出 `ValueError`；`predict_latest()` 将加载错误转为显式的 `unavailable`，不会静默预测或重新训练。

特征名字相同也不能交换列：例如温度均值落入温度delta的位置，会同时应用错误的scaler均值/方差及模型系数，输出仍可能是正常数字，因此必须在推理前校验顺序。

推理使用模型包自己的窗口配置（本轮6/2），不跟随之后改动的 `dataset_config.json`。从原始表取**最新6点**后才检查：30分钟严格连续、数值有效、来源为模型已训练的SIMULATED。缺点、重复时间、缺值或来源不适用时直接 `unavailable`，不向前搜索旧的连续窗口、不插值或跳过坏点。正常时调用与训练相同的 `_features()`，按固定列顺序执行 `scaler.transform()` 和模型预测，没有fit。

接口成功结果示例：

```json
{"status":"ok","prediction":"NORMAL","probability":0.1380187288040352,"probability_of":"WATCH","model_version":"attention_v1","window_start":"2026-10-21T06:30:00+00:00","window_end":"2026-10-21T09:00:00+00:00","source_type":"SIMULATED","evidence_type":"MODEL_OUTPUT","horizon_minutes":60}
```

`probability` 始终是 P(WATCH)，并非 NORMAL 的概率。预测时间为 `window_end` 后1小时，不会把旧窗口平移到请求时间；这里未定义额外的墙钟过期阈值，使用者及Agent必须检查实际窗口时间。模型只学到合成数据的RULE_v1标签，概率未校准，不能替代真实植物风险判断。

第5工具 `predict_next_attention()` 无参数，使用统一外壳 `status/source/time/data/error`，`source=MODEL_OUTPUT`，data即推理结果（包括版本及 `evidence_type=MODEL_OUTPUT`，不可用时也保留）。首页Agent可问：

> 预测接下来一小时要不要关注，并结合天气和养护知识说明。

系统提示要求调用对应证据工具，并分别表述模型预测、天气证据、植物知识；说明版本、概率、窗口时间、不确定性与SIMULATED适用范围。预测不能填补天气/知识查询失败的证据空缺。展开调用链可看第五工具的参数、结果、耗时及模型版本。

### 验收证据与复现

```bash
# 本地推理、契约校验、缺口及原生Agent工具协议测试
.venv/bin/python -m unittest -v test_ml_infer
# 启停两次全新服务进程，在禁止fit的情况下请求推理接口
HF_HUB_OFFLINE=1 .venv/bin/python verify_b06_restart.py
# 可选：真实LLM联网验收，只使用临时生成的模拟历史及公开天气/知识
HF_HUB_OFFLINE=1 .venv/bin/python verify_b06_agent_live.py
```

- 重启验收已通过：两个不同PID的正常FastAPI启动进程均成功推理，期间禁止 `LogisticRegression.fit` 和 `StandardScaler.fit`；返回相同结果，模型/manifest哈希完全未变。见 `verification/b06_restart.json` 和 `.log`。
- manifest特征前两列故意交换的测试确认 `load_model()` 抛出 `ValueError`，推理接口返回 `unavailable`。测试在临时模型副本上修改，正式manifest保持正确。
- 原生工具协议测试真实执行本地已保存模型的预测工具，并验证天气和知识证据分开、失败注明、样本表字节不变；LLM、天气超时、知识返回为测试驱动，不能据此宣称真实模型自主决策验收已通过。
- 两次真实LLM联网尝试都在首轮连接失败，尚未产生工具链或最终回答；报告 `model_error`，见 `verification/b06_agent_live.json` 和首次尝试记录。当前**完整联网Agent验收未通过**，需要模型服务连接恢复后复验。

“完全重启后加载”证明文件中真正保存了推理所需的已拟合状态，脱离训练进程仍能恢复；本轮还用禁止fit及文件哈希不变排除了现场重训。“现场重新训练后预测”只能证明当前训练路径能工作，不能证明磁盘模型完整、加载路径正确或能跨进程复现。

## B06 健壮性收尾：LLM 有限重试与失败证据

`llm.py`（`/api/ask`）与 `agent.py`（`/api/agent`）共用 `llm_retry.py`。每次模型请求最多尝试3次：首次请求失败后等1秒，第二次失败后等2秒；第三次仍失败就抛出。仅对上游HTTP **502/503/504**、SDK连接错误和超时重试。400、401、403、429、500等其他错误不重试。SDK自身的 `max_retries=0`，避免叠加隐藏重试；没有备用模型或无限重试。

502 Bad Gateway 表示网关/代理未能从上游获得有效响应，属于上游服务链路错误，不能据此认定本地工具失败。有限重试可能跨过短暂故障，但不能保证上游恢复。一次模型请求仍使用原有45秒超时；若每次都耗尽超时，三次尝试连同等待约需138秒（另有网络开销）。Agent原有最多5轮上限不变，重试不计成新一轮。

每次失败和最终成功都打印日志，例如连续502会输出：

```text
[llm.attempt] attempt=1 error_type=InternalServerError status_code=502
[llm.attempt] attempt=2 error_type=InternalServerError status_code=502
[llm.attempt] attempt=3 error_type=InternalServerError status_code=502
```

如果第三次恢复，则最后一行为 `attempt=3 error_type=None status_code=200`。attempt针对每次独立的模型请求重新从1开始，不是工具调用编号。日志不打印key、请求头或上游原始错误正文。

重试范围仅包围 `chat.completions.create()`，不会重跑问答历史写入、重新检索、重新执行Agent工具或丢弃已有messages。第二轮总结失败时，重发的是同一份包含工具结果的上下文；已经记录的 `tool_calls` 保留，`sequence` 不重新编号。

最终失败后，两个API都增加：

```json
{"llm_error":{"status_code":502,"message":"模型调用失败，请检查网络及平台的tools支持情况。"}}
```

这里的 `status_code` 是**上游**HTTP状态；连接中断或超时没有上游HTTP响应时为 `null`。根层API响应的HTTP状态沿用原有映射，例如上游401仍由项目返回HTTP502，但 `llm_error.status_code=401`。message为本地安全提示，不暴露上游原始正文。成功响应保持原结构。

如何区分失败阶段：

- `/api/agent` 的 `tool_calls=[]`、`iterations=1`：首轮模型请求失败，工具尚未执行；终端没有本次请求的 `[agent.tool]`。
- `/api/agent` 的 `tool_calls` 非空、`iterations>=2` 且有 `llm_error`：已有工具实际执行并留下结果，后续模型回答失败。逐条看工具自己的 `status`；不能将成功的工具证据说成未执行。
- `/api/ask` 本来不提供Agent工具，失败返回 `tool_calls=[]`、`used_state/source_type`、原有 `detail` 及新的 `llm_error`。用户问题只写入历史一次，不保存伪造的assistant回答。

以上判断针对模型调用错误；Agent参数校验失败、空模型回答等本地错误应同时看 `answer/detail`，不要只看调用条数。

故障注入复现（不需要修改真实base_url）：

```bash
GREENMATE_RETRY_EVIDENCE=verification/llm_retry_failures.jsonl \
  .venv/bin/python -m unittest -v test_llm_retry
```

测试用SDK的模拟HTTP传输返回502等状态或抛出连接/超时异常，验证真实请求次数、1s/2s等待参数、attempt日志、非重试错误，以及已执行工具只执行一次且证据保留。测试把sleep替换为空等待，避免故意消耗时间；生产逻辑仍真实等待1s/2s。证据JSONL会追加写入。

真实连续5次API验收（使用配置中的平台和模型）：

```bash
HF_HUB_OFFLINE=1 .venv/bin/python verify_llm_retry_live.py
```

该脚本顺序调用真实 `/api/agent` 路由（本地ASGI客户端），真实请求LLM；仅在临时数据库生成模拟样本，使用公开北京坐标及植物知识，不读取或发送正式数据库状态/历史。完整回答、工具链和重试日志见 `verification/llm_retry_live_5.json` / `.log`。天气证据不可用但LLM能明确说明缺失并完成回答，仍属于正常回答；模型请求失败或达到5轮上限不计成功。平台网络稳定性以实际计数为准，不用离线模拟结果替代。

本轮实测记录：全量82项测试通过；首批真实请求3/5正常，保留在 `verification/llm_retry_live_5_first_batch.*`；第二批同样3/5正常，保存在 `verification/llm_retry_live_5.*`。两批都有重试后恢复的真实记录，也都有三次仍连接失败的记录；失败时 `llm_error.status_code=null`，因为SDK未取得上游HTTP响应。已有工具的失败请求仍保留完整工具链。**目前“至少4/5正常回答”的上游稳定性验收未达标**，未为凑通过率增加重试次数、切换模型或改动工具定义。

## B07 第1步：单页产品与集中配置

```bash
./run.sh
```

脚本自动进入项目目录、激活 `.venv`、检查 `.env`、验证配置后启动 `127.0.0.1:8100`。没有 `.env` 时给出复制 `.env.example` 的中文提示并退出；缺key时清晰提示联网问答不可用，允许本地演示。需要其他端口可执行 `./run.sh 8101`。它不会自动安装依赖、生成数据或重训模型。

`settings.py` 是唯一环境变量读取入口，使用项目根目录 `.env`（不受启动终端目录影响），显式环境变量优先。集中管理 `GREENMATE_API_KEY / GREENMATE_BASE_URL / GREENMATE_MODEL / WEATHER_LAT / WEATHER_LON / DB_PATH`。默认DeepSeek、北京及项目根目录 `greenmate.db`；相对DB_PATH基于项目目录解析。无效地址、空模型、空数据库路径或非法经纬度在启动阶段报中文错误。配置修改后重启服务，密钥不返回页面或写入日志。`config.py` 仅保留旧导入兼容，不再自行读环境。

首页为环境、问答、知识、预测四区块。问答卡可切换普通问答与Agent，展开SQLite问答历史和工具证据；环境卡可查看最近24小时历史；知识卡提供列表、语义搜索和热加载；预测卡展示磁盘模型输出及指标。所有内容使用原生JS与本地CSS，无外部字体、前端框架或CDN。

补充只读接口 `GET /api/environment/history` 和 `GET /api/knowledge/search?query=...` 供单页展示。错误统一为 `{"error":{"code":"...","message":"中文原因","hint":"处理建议"}}`；HTTP错误、参数校验、未预期异常及LLM失败均使用此结构。原有 `detail/llm_error/tool_calls/used_state` 等证据字段保留。预测不可用返回HTTP503和PREDICTION_UNAVAILABLE，推理工具本身仍沿用B05统一工具外壳，不改变工具定义。

前端统一请求函数处理HTTP错误、无法连接和非法JSON，每个区块独立显示中文提示，单项失败不会使整个页面空白。未知异常不将堆栈或上游私密正文发给页面。断网时旧读数与历史证据保留并标明失败；预测刷新失败时清除旧的预测结论，避免被当成本次结果。

六步“点什么、看什么、说明什么”见 [DEMO.md](DEMO.md)。按B01–B06能力顺序组织，先理解环境，再理解记忆、外部证据、检索、工具和预测；接口只承载这些能力，不是演示听众需要记住的内容。

```bash
HF_HUB_OFFLINE=1 .venv/bin/python -m unittest -v test_b07
```

页面测试脚本 `verification/b07_ui.cjs` 使用桌面捆绑Playwright，不给项目新增依赖。报告及桌面/手机/断网截图保存在 `verification/b07_ui.*`、`verification/b07_desktop.png`、`verification/b07_mobile.png`、`verification/b07_offline.png`。测试使用临时数据库，LLM及天气交互夹具仅用于验证页面呈现，不能替代真实联网验收。

本轮最终验收：86项后端测试通过，12项浏览器交互检查通过，页面未捕获到JS异常；真实run.sh在独立本机端口启动成功。截图已检查桌面和390px手机布局。浏览器已模拟断网，四个区块均显示中文提示，Agent总结失败仍显示已执行工具链。测试服务已停止，正式数据库与现有8100服务未被修改。

## B07 第一遍 S1：完整分析链与分析档案

固定问题只定义在 `analysis.ANALYSIS_QUESTION`，后续不得改动：

> 分析当前番茄生长环境状态以及接下来值得关注的变化，并说明判断依据。

POST请求不接受自定义question。原有环境、问答、知识、预测区块保持，新增“分析档案 · S1”。

### 准备与演示

```bash
.venv/bin/python prepare_s1.py
# 停止旧服务后重新启动，让B02加载准备后的持久化快照
./run.sh
```

`prepare_s1.py` 先检查现有最近3小时是否已有连续稳定SIMULATED段（温度29–30°C、波动不超过0.5°C，湿度波动不超过2个百分点）。符合则复用；已稳定且在半小时网格上的部分点允许补齐。没有重叠样本时生成6个连续半小时点：温度29.4–29.6°C、湿度64.9–65.3%、光照12000 lux，标记SIMULATED / `s1_stable`。遇到冲突的非稳定段或时间网格不一致会明确拒绝，不覆盖、删除、移动原样本，也不为了产生故事插入异常。通过B02现有 `update_state()` 保存与末点一致的模拟当前状态，时间戳保留真实保存时刻。

脚本不训练或修改模型。本轮保留原336条seed_demo，追加6条S1稳定点，共342条；准备锚点保存在 `s1_preparation.json`。分析本身不会自动采样或运行准备脚本。

在首页“分析档案”点“运行一次分析”；可留空时间使用请求开始时的当前时间，也可填准备文件中的带时区时间以明确复演。默认地点北京，仅作档案标识，不会触发地理查询。展开结构化判断、证据状态、判断限制和完整JSON，再查看LLM解释。最近5次编号可点击，旧编号也可粘贴到“按run_id回查”。

准备的模拟段不会自动推进时间，30分钟后默认当前时间可能不足6点，应如实标unavailable；已有档案始终可按run_id读取。如果重新设置过B02状态，过去锚点之后的当前快照不会被伪装成过去状态，当前状态证据会unavailable。需要完整复演时直接回查已归档编号。

### 时间、证据与结构化判断

`run_analysis(analysis_time=None, location="北京")` 将带时区时间归一为UTC；不接受无时区或未来的分析锚点。时间锚点在开始时固定，后续LLM耗时不移动窗口：

- 当前状态：复用 `get_current_environment()` 底层B02快照，保留其原时间戳；快照晚于锚点时标unavailable，不使用未来读数。工具retrieval time是取证时间，不是测量时间。
- 历史：直接读取B02 `environment_samples` 的 `(analysis_time-3h, analysis_time]`，元数据 `history_window.end` 严格等于analysis_time。至少6点、间隔30分钟、无重复/断档/无效数值，且末点距锚点不超过30分钟；否则不计算趋势或拼凑预测。
- 预测：把同一历史窗口传给B06共用推理实现 `predict_window()`，按模型包窗口配置取末6点。校验并加载已保存attention_v1及scaler；不读取锚点后的样本、不回退到更早窗口、不fit。MODEL_OUTPUT原样保留，包括WATCH。记录输入特征、原始样本ID、模型摘要与训练时间。
- 时间字段：`window_start/window_end` 是模型输入区间；`target_start/target_end` 是输入末点后的未来预测区间。历史查询窗口终点、实际最后采样点、快照时间可相差少量时间，均单独保留，不篡改时间戳去凑一致。
- 程序判断：包含current_state、history_window、recent_trend、predicted_attention、evidence_status、judgment_limits，标记 `generated_by=PROGRAM`。趋势以首尾delta描述stable/rising/falling，同时给均值、min/max与首尾值。显示容差为温度0.5°C、湿度2个百分点、光照1000 lux，仅用于描述波动，不是新的农艺风险阈值或规则引擎，不产生或改写WATCH/NORMAL标签。
- 本链不调用天气或RAG，二者状态明确为unavailable；无土壤湿度、番茄阶段或适宜性知识，不能判断浇水需求。原有其他页面能力不受影响。

程序先生成并保存结构化判断，LLM只解释该JSON，沿用既有平台配置和有限重试。提示词禁止新增证据、适宜阈值、改变模型输出或假定天气；输出与程序判断分开保存。LLM解释失败时answer为空，`judgment.explanation_status=unavailable` 和 `judgment.llm_error` 说明原因，run_id与证据仍可回查，不用程序模板冒充LLM解释。

### 档案与接口

`analysis_runs` 一张表，字段为run_id、analysis_time、location、question、state_json、history_window_json、prediction_json、judgment_json、answer、evidence_status_json、created_at。LLM请求前先插入证据快照；完成时只更新answer和解释元数据，原证据不重取。

- `POST /api/analyze`：body可省略，或 `{"analysis_time":"2026-10-21T20:14:32.457357+08:00","location":"北京"}`；返回完整档案。参数错误仍使用B07统一中文错误。
- `GET /api/analyze/{run_id}`：只从SQLite反序列化当时快照与答案，不重新取证、推理或调用LLM。
- `GET /api/analyze`：返回固定问题与最近5条档案索引。

run_id以UTC锚点和随机后缀组成，既区分同一时刻的多次执行，也能在关页面、重启或数据更新后指向当时的输入、预测、程序判断及解释。读取旧档案不受之后改变环境或模型文件影响；它是证据回查，不是用现有状态重新计算一遍。

```bash
HF_HUB_OFFLINE=1 .venv/bin/python -m unittest -v test_analysis
# 已准备S1后，真实LLM解释 + API回查 + 新进程SQLite回查
HF_HUB_OFFLINE=1 .venv/bin/python verify_s1_live.py
```

真实联网证据见 `verification/s1_live.json` / `.log`；首次成功档案另存 `s1_live_first_run.*`，SQLite原档案同样保留。浏览器测试 `verification/s1_ui.cjs` 使用临时数据库、真实本地模型/程序/归档，解释回复为明确UI夹具，报告与截图见 `verification/s1_ui.json`、`s1_desktop.png`、`s1_mobile.png`，不能与真实LLM报告混淆。

本轮S1验收完成：93项后端测试、8项分析档案浏览器检查通过。正式数据库保留336条seed_demo并新增6条s1_stable；真实LLM解释成功。示例档案 `run_20261021_121817_f8981b4ccb7b`：历史窗口end与analysis_time完全一致，当前/历史/预测均ok，温度29.4–29.6°C、湿度64.9–65.3%，attention_v1实际输出NORMAL、P(WATCH)=0.0033573094731232534。API回查和关闭解释进程后新Python进程读取SQLite，内容均与原响应一致；分析未改变采样表或模型文件。天气与植物知识为unavailable，未新增来源。另有稳定趋势+WATCH的故障隔离测试，确认不会人工改标签。

## B07 第一遍 S2：只改变过去的历史过程

新增业务模块仅 `scenarios.py`；`analysis.py`、固定问题、`llm.py`全部提示词、`agent.py`和attention_v1模型/manifest均未修改，前后哈希见 `verification/s2_baseline_hashes.json` 与 `verification/s2_live.json`。继续复用S1完整分析链，没有天气或知识等新增证据。

### 场景准备与幂等

`apply_scenario(name, analysis_time=None)` 提供两个透明的六点模拟过程，每点间隔30分钟：

| 场景 | 温度序列（°C） | 当前温度 | 全程湿度/光照 |
|---|---|---:|---|
| S1_stable | 29.8、29.9、29.8、30、29.9、30 | 30 | 65% / 12000 lux |
| S2_ramp | 25、26、27、28、29、30 | 30 | 65% / 12000 lux |

所有点 `source_type=SIMULATED`，`sim_scenario` 为请求的场景名。两个末点数值及时间完全一致，只让过去温度过程产生变化。当前状态的timestamp表示受控模拟锚点，不伪装为真实传感器测量时间。

场景切换在一个SQLite事务中替换该3小时窗口内的受管模拟点，并更新现有current_state，随后刷新B02缓存。受管名称为S1_stable、S2_ramp及兼容S1准备段的s1_stable。不能把两段过程同时堆进同一窗口，否则会产生重复时间和伪趋势。已归档analysis_runs存有完整快照，切换不改写旧档案。

原seed_demo、真实观测及其他非受管记录不删除；若它们与目标窗口冲突，返回中文错误，要求选择无冲突时间。默认复用最近30分钟内的活动场景锚点；没有可用锚点时使用当前时间。前端首个场景完成后保留锚点，第二次显式使用同一锚点。相同场景、相同锚点、相同六点重复应用新增0条，ID不变；30分钟后另选新锚点属于新时间窗口，不是重复插入同一组点。

### 接口与页面

- `POST /api/scenarios/apply`：`{"name":"S1_stable"}` 或S2_ramp，返回samples_written、samples_removed、sample_count、analysis_time、current_state。可选analysis_time用于严格复演。
- `POST /api/analyze/scenario`：同样的请求体；先应用场景，再调用完全未修改的 `run_analysis()`，返回run_id、scenario准备结果与完整run。场景入口串行执行，避免两次切换交错。
- `GET /api/analyze/compare?run_a=...&run_b=...`：只读取归档，无LLM、重取证或重算模型。返回Current、Recent trend（方向及数值）、Predicted attention、Structured judgment摘要、Evidence status和Answer首段共六行；structured_delta列出changed和unchanged，并给出实际窗口温度序列以检查覆盖。

`structured_delta` 排除run_id、原始点ID、取证/创建时刻和LLM措辞等非业务差异；分析时间、地点、固定问题、证据状态、判断限制、当前值、趋势、预测和输入特征均可核对。如果业务字段完全一致，会明确要求核对窗口是否覆盖升温段，不能仅凭S2这个名字宣称判断发生变化。预测不可用时同样不伪装成有效标签对照。

首页新增“S1/S2对照”区块：依次点“运行S1_stable”“运行S2_ramp”，自动显示相同固定问题原文、“两次提问完全相同”、共同时间锚点、两份run_id和对照表。展开变化/不变字段和历史窗口核对；重新运行可生成另一份档案，但重复场景不会重复造样本。原分析档案与其他页面功能保留。

### 实测结果与边界

真实LLM验收两次均成功，使用同一分析时间和完全相同当前状态：

| 项目 | S1_stable | S2_ramp |
|---|---|---|
| 当前温湿光 | 30°C / 65% / 12000 lux | 完全相同 |
| 温度趋势 | stable，29.8→30，Δ0.2，均值29.9 | rising，25→30，Δ5，均值27.5 |
| 原始模型标签 | NORMAL | NORMAL |
| P(WATCH) | 0.0020009408（约0.20009%） | 0.0000104742（约0.00105%） |

本次结构化趋势、温度均值/delta及预测概率改变；当前值、湿度/光照过程、模型标签、证据状态、问题及判断限制未变。标签未翻转，概率反而下降，这是已保存模型的真实输出。不能据此说升温已证实更危险，也不能为符合直觉把S2改成WATCH；v1是合成数据RULE_v1基线，不是已验证的番茄风险模型。两个窗口都确实覆盖完整六点过程，绝非窗口漏掉升温段。

S2证明的是：当前快照相同不代表过程相同；历史特征使程序能够区分“接近30°C一直稳定”和“刚从25°C升至30°C”，模型也会接收不同的均值与变化量。对照关注可追溯的业务证据变化，而不是仅比较LLM措辞是否不同。

实测编号：

- S1：`run_20261021_121432_1734c77d303c`
- S2：`run_20261021_121432_d60da710f085`

```bash
HF_HUB_OFFLINE=1 .venv/bin/python -m unittest -v test_scenarios
# 实际应用两个模拟场景并调用原固定分析链、真实LLM、compare接口
HF_HUB_OFFLINE=1 .venv/bin/python verification/s2_live.py
```

真实结果与旧档案/冻结文件哈希保护证明见 `verification/s2_live.json` / `.log`；页面测试 `verification/s2_ui.cjs` 复用既有S1 UI解释夹具，真实运行场景、模型、归档和对照，报告/截图见 `verification/s2_ui.json`、`s2_compare.png`、`s2_mobile.png`。页面夹具不作为真实LLM解释证据。

S2最终验收：96项后端测试、7项页面检查通过；真实LLM两次解释成功，旧归档与冻结文件哈希保持一致。对照记录得到8个变化字段、40个不变字段；重复应用同锚点S2新增0条。页面检查覆盖自动对比、相同问题、相同当前值、历史轨迹差异、模型标签相同的如实展示、旧S1档案保留、手机布局和断网提示。

## B07 第一遍 S3：只增加已有的未来天气证据

`analysis.run_analysis(analysis_time=None, location="北京", include_weather=False)` 默认沿用S2：不调用天气工具，weather为unavailable、weather_expectation为unknown、attention_adjustment为none。传true时只复用已有 `tools.get_weather_forecast(location)`，不新增天气请求、工具、知识来源或依赖。固定番茄问题、llm.py中的所有提示词、agent.py、tools.py以及attention_v1模型/manifest均未改动，哈希见 `verification/s3_baseline_hashes.json`。S2的历史哈希报告保留；S2回归测试仅解除本轮明确允许扩展的analysis.py哈希冻结，提示词与模型仍冻结。

### 请求、归档与时间语义

- `POST /api/analyze`：可选请求体 `{"location":"北京","include_weather":true}`，仍支持带时区的analysis_time。
- `POST /api/analyze/scenario`：`{"name":"S1_stable","include_weather":true}`；做成对对照时，第二次须传第一次返回的analysis_time。场景准备和内部分析逻辑不变。
- 两个接口默认include_weather=false，并严格校验布尔值。`POST /api/scenarios/apply`只负责原场景准备，不接天气。
- `GET /api/analyze/{run_id}`按原方式完整回查。天气证据存入已有judgment_json，路径为 `judgment.weather_evidence`，无需新表或迁移；LLM失败时证据仍已归档。

天气证据包含source_type=WEATHER_FORECAST、source/provider、time/retrieved_at、forecast_time.start/end、status、result、error，以及analysis_time和excluded_past_count。source与time分别直接映射工具的source和time。result保留工具的地点、单位等元数据及**过滤后采用的逐小时预报点**。

时间比较使用带时区的真实时刻，精确到微秒；只采用timestamp >= analysis_time的点，等于锚点允许采用。forecast_time表示过滤后首末预报的有效时间，retrieved_at表示取得响应的时间，两者不可混用。全部点早于锚点时，weather为error，错误明确写“预报时间早于分析时刻”，结果为空且不用于未来判断；空响应或缺少合法时间/数值也记error。网络失败沿用工具的unavailable，其他内部证据和模型推理继续执行。

历史是锚点之前**已发生**的过程（本演示仍为SIMULATED）；天气是外部地点**未来有效的预报**，本身存在预测误差。拿过去天气解释未来会发生时间错配；取证时间晚也不能把已过期的预报变成未来证据。回查旧锚点时，本次获取的天气不能冒充“当时可获得的历史预报”。天气约12小时与模型未来1小时区间分别保存和说明。

### 程序判断与边界

判断新增weather_expectation、attention_adjustment和adjustment_reason：对采用预报的首尾温度差复用已有0.5°C趋势显示容差，超过容差标warming/cooling，并raise对**外部升降温变化**的关注；首尾变化较小记unknown/none，同时展示区间最低/最高值。没有可用天气一律unknown/none。不因降温自动lower：没有番茄适宜阈值、阶段和土壤证据，不能把降温一概当成安全。该描述不是新的番茄风险规则或模型标签；模型原始NORMAL/WATCH及P(WATCH)保持不变，结构化数据生成后交给原有提示词解释。

已有天气工具只提供温度、空气湿度，没有降雨或光照，故本轮不生成rainy/low_light结论；不添加字段或调用其他来源补齐。外部预报不能替代内部实测，也不据此决定浇水。新增限制写在程序生成的判断数据中，未改LLM系统提示或固定问题。

### 页面操作与验证

启动仍为 `./run.sh`。首页“分析档案”可勾选“包含外部未来天气”；其下“S3对照”依次点“S1 · 不含天气”“S1 · 包含天气”。两个按钮保留同一锚点，均应用原S1_stable；并排展示当前值、历史趋势、模型、天气元数据、关注调整依据及LLM解释。逐小时证据可折叠展开，各编号可回查完整档案。天气不写回当前环境；网络失败显示中文原因，已有结果保留。

```bash
HF_HUB_OFFLINE=1 .venv/bin/python -m unittest -v test_s3_weather
HF_HUB_OFFLINE=1 .venv/bin/python -m unittest discover -q
# 真实天气工具 + 真实LLM，导出本次新生成的S1模拟场景证据
HF_HUB_OFFLINE=1 .venv/bin/python verification/s3_live.py
```

本轮102项后端测试通过，包含默认不调用天气、两个入口透传、精确时间/跨时区过滤、全部过期、真实工具Timeout降级、LLM失败归档以及WATCH原样保留。6项浏览器检查覆盖相同内部状态、并排元数据/解释、预报时间校验、run_id回查、手机布局、断网提示；UI使用隔离数据库及明确标注的天气/LLM夹具，报告与截图见 `verification/s3_ui.json`、`s3_compare.png`、`s3_mobile.png`，不能作为真实上游服务证据。

真实验收另存 `verification/s3_live.json` / `.log`：同一内部状态30°C / 65% / 12000 lux、相同六点稳定历史，attention_v1均为NORMAL、P(WATCH)=0.0020009407617377047。无天气为unknown/none；真实OPEN_METEO预报2026-10-25 08:00 UTC的11.9°C至19:00 UTC的9.9°C（区间最低9.8°C），有天气为cooling/raise。LLM明确引用这段外部预报并说明不修改内部模型标签；所有采用点均不早于锚点，两次解释成功，回查一致，受保护文件哈希一致。

- 无天气：`run_20261025_072230_ad1d2990f821`
- 含天气：`run_20261025_072230_33ff637872f1`

工具封装的取证time在两次运行间自然不同；内部状态是否相同以状态数据及其原始timestamp、历史窗口、模型输入/输出为准，不把HTTP取证时刻差当成状态变化。

## B07 第一遍 S4：知识工具与证据分歧

页面新增“S4 证据分歧”，通过 `S4_conflict`、`include_weather` 与 `include_knowledge` 运行。证据卡保留来源/时间身份与引用；工具链显示实际调用和 adopted；冲突不被合并成单一恶化结论。固定问题与 B06 模型不变。

实现、接口、数据库向后兼容迁移和验收说明见 [S4.md](S4.md)。真实联网记录在 `verification/s4_live.json`，界面测试数据与截图在 `verification/s4_ui.json`、`s4_desktop.png`、`s4_mobile.png`；两种验证不得混作真实天气证明。
