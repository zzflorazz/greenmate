# 首页 hero / 三维温室验收

启动（在项目当前目录）：

```sh
.venv/bin/uvicorn main:app --reload --port 8100
```

打开 http://127.0.0.1:8100 。原卡片仍在工作台；两个首屏按钮分别跳至环境和分析档案。Three.js 为本地 r160 模块，运行时无 CDN 请求；原始 MIT 许可保存在 vendor/THREE-LICENSE.txt。

映射只改变示意，不修改实际读数：

| 输入（超出时按端点显示） | 视觉响应 |
| --- | --- |
| 光照 0–24000 lux | 阳光强度 0.3–2.7，线性 |
| 温度 14–34°C | 阳光色从 #a9cfe6 到 #ffb877 |
| 空气湿度 0–100% | 雾密度 0.012–0.032；玻璃 opacity 0.11–0.23 |

每帧按实际时间指数插值，兼顾不同帧率。六株番茄、四面玻璃墙、门窗、四根立柱、半圆柱屋顶及九道同方程拱肋均为几何体。没有粒子背景。相机朝向固定，ResizeObserver只调整比例和完整容纳场景所需的距离。

减少动态效果关闭自转与叶片摆动，用户主动拖动仍可旋转。IntersectionObserver和document.hidden共同决定是否保持requestAnimationFrame；恢复可见时也须仍在视口内。WebGL不可用或模块加载失败时保留SVG温室，首个成功渲染后才淡入canvas；上下文丢失也回退线稿。

## 自动验证

- `HF_HUB_OFFLINE=1 .venv/bin/python -m unittest discover -q`：117项通过（含2项新增本地资源缓存/路径边界检查）。
- `hero_ui.json`：13项浏览器检查通过，包含真实WebGL、首次数据先于模块加载的竞争、实际API驱动平滑映射、键盘焦点、拖动惯性、实时减少动态效果切换、离屏/隐藏暂停与恢复、1440/850/450/390布局、资源/WebGL降级，以及原问答/Agent/知识/模型/S1–S4操作。
- `hero_probe.cjs` 不注入观察器，检查正常页面真实渲染且无控制台错误。`hero_ui.cjs` 只在测试浏览器加载的vendor响应中为renderer添加观察器，记录实际场景材质/灯光和渲染帧数，不修改磁盘vendor或生产代码。
- 自动页面回归使用隔离SQLite数据库。天气/LLM在`hero_ui_server.py`中有明确测试夹具，RAG、状态、场景、持久化模型使用实际项目实现；不把夹具当作真实上游成功证据。
- `hero_live_weather.json`为独立的真实天气按钮联调（设置GREENMATE_UI_LIVE_WEATHER=1，保留原main.fetch_weather），不调用LLM。对应截图`hero_live_weather.png`。
- 图片：`hero_desktop.png`、`hero_mobile.png`、`hero_mobile_full.png`、`hero_fallback.png`。

浏览器脚本通过已有`webapp-testing/scripts/with_server.py`启动临时服务执行，使用机器现有的Node Playwright和Chromium；项目没有新增浏览器依赖、npm或构建工具。正式数据库不参与测试。原有所有后端函数/请求模型经AST对照未变，analysis/agent/db/ml/scenarios/llm/tools文件哈希与本轮开始一致。后端产品变更仅为`/vendor/{filename}`静态路由。
