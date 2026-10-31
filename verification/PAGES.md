# 六页界面验收记录

运行原命令 `.venv/bin/uvicorn main:app --reload --port 8100`。首页、环境、问答、知识、预测、分析分别为 `/`、`/environment`、`/conversation`、`/knowledge`、`/prediction`、`/analysis`。

## 保留边界

全部原有 main.py 内容逐字保留，仅在末尾追加 StaticFiles 和白名单页面路由。analysis、agent、db、tools、llm、ml_train、ml_infer、scenarios 及模型文件与本轮开始的SHA256一致；原API、请求字段、固定问题/提示词、证据标注、模型版本与输出均不改动。测试在独立SQLite文件中运行，不改正式数据库。

旧问答路由测试中“首页必须有ask-form”改为“首页有/conversation入口，问答页有ask-form”，符合本轮明确授权的拆页。新增页面、静态资源、非法页面路径与六张JPG大小测试。

## 已通过

- `HF_HUB_OFFLINE=1 .venv/bin/python -m unittest discover -q`：119项通过。
- `pages_probe.cjs`：不注入观察器，六页真实加载，本地图片与脚本可用，1440px无溢出，控制台无错误；截图为pages_*.png。
- `pages_ui.cjs` / `pages_ui.json`：14项分组检查通过。六页原按钮、导航高亮、首次数字动画、API跨页同步、阴影和本地反射、鼠标拾取/悬停/双击、键盘复位、知识实际检索/索引重载、持久化模型预测/指标、全部S1–S4流程/知识开关/回查、390px无溢出、减少动态效果、缺图/Three加载失败/断网兜底均覆盖。
- 测试观察器只在浏览器加载的vendor响应中包装render记录实际场景、相机与draw call，未改变磁盘Three文件。实测约91次主渲染draw call，低于120。生产初始化使用真实WebGL、软阴影与512×256天空到地面渐变反射贴图。
- `pages_live_weather.cjs` / `.json`：单独使用真实现有天气接口，从环境页点击真实天气后回到首页核对读数及REAL_WEATHER徽标，隔离数据库、不调用LLM。
- 开发用临时服务通过已有webapp-testing的with_server.py管理并回收；正式8100服务另外保留运行。

六张配图由内置image_gen按用户场景提示词分别生成，再用本机已有Pillow裁切为指定尺寸并编码成≤250KB JPG；项目未新增Pillow或其他运行依赖。提示词与用途在 assets/img/PROMPTS.json，页脚标明“AI生成，仅作装饰”，不把配图当实测数据。

## 交互与降级

原生startViewTransition仅在支持且未减少动态效果时启用，180ms离场完成后才进行文档导航，避免在活跃过渡中跳转造成浏览器Abort错误；下一页轻量180ms入场，不支持则直接导航，无polyfill。返回缓存页面时清除离场状态。

数字动画仅首次进入视口，真值来自/api/state；减少动态效果时直接显示实际值。视觉光/雾不读取动画中间值，直接接收原始状态。回到首页或页面重新可见时重新获取原接口，保证环境页切源后的数据一致。

缺图通过强制404复现，图片隐藏、容器显示渐变和线性植物SVG；不篡改或删除正式图片。Three加载失败保留SVG温室。预期的缺图/模块失败在单独页面测试，不混入正常页面“无控制台错误”的记录。

所有各页静态DOM ID在各页脚本开头一次性读取并判空；后续通过已校验的节点表访问，保留旧渲染逻辑且不操作其他页面DOM。共用工具只定义于app.js。三维模块只在首页加载。
