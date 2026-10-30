# 植物知识库

编辑 `plants.json` 后调用 `POST /api/knowledge/reload`，无需重启服务。
热加载会重新计算知识向量并覆盖 `index.json`；返回 `index_ready: true` 表示重建成功。
每条记录保留 `name`、`light`、`water_freq`、`tips` 四个非空字符串字段。
其中绿萝“7-10天”为教学示例参考周期，不是固定浇水计划；实际需检查盆土并考虑环境、季节和盆器。

养护内容经以下资料核对并简要改写：

- 绿萝：[NC State Extension](https://plants.ces.ncsu.edu/plants/epipremnum-aureum/)
- 龟背竹：[NC State Extension](https://plants.ces.ncsu.edu/plants/monstera-deliciosa/)
- 发财树：[NC State Extension](https://plants.ces.ncsu.edu/plants/pachira-aquatica/)
- 文竹：[NC State Extension](https://plants.ces.ncsu.edu/plants/asparagus-setaceus/)
- 多肉、仙人掌：[RHS Growing Guide](https://www.rhs.org.uk/plants/types/cacti-succulents/houseplants/growing-guide)

## 本地向量检索

- 模型为指定的 `sentence-transformers/all-MiniLM-L6-v2`，输出 384 维向量，模型文件缓存在项目 `.models/`。
- `index.json` 保存模型名称、知识内容指纹以及每条知识的向量。启动时指纹匹配则直接读取；文件损坏或知识内容改变时重建。查询向量按需计算，不存 SQLite。
- `/api/ask` 优先调用 `vector_search()`，按余弦相似度返回最多两条，且分数须达到 `rag.MIN_SIMILARITY=0.45`；无匹配时返回空列表。该门槛用于过滤低相关结果，不代表匹配概率。模型加载、向量计算或索引出错时打印日志并调用原 `simple_search()`。
- 索引或模型更新后应重新执行 reload，不能混用不同模型生成的向量。

### 中文排序限制与实测

[官方模型卡](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)标注该模型语言为 English；本项目按用户选择继续保留该模型。
当前中文样例“植物缺水怎么办？”的关键词结果为空，真实向量结果为龟背竹、文竹，均含浇水建议，未达到原验收要求的绿萝／多肉排序。
该结果说明向量路径确已工作，但不能据此宣称中文语义排序质量已经达标。没有添加关键词替换、固定植物优先级或针对样例的硬编码。
详细余弦分数见 `vector_verification.json`，由真实模型运行生成；单元测试使用固定测试向量，只验证计算、缓存、接口和回退逻辑，不用于证明模型质量。

## B07 S4：番茄与可追溯引用

`plants.json` 新增番茄条目 `tomato_heat_01`，含温度、空气湿度、光照、高温关注条件与原始资料链接。所有维护条目有稳定 `id`；`simple_search` 与 `vector_search` 的返回项均附 `citation: {id, name, snippet}`，片段直接来自条目原文。

显式提及植物名时，检索结果约束为该物种（通用于所有条目），防止中文向量结果误用其他植物知识；其余查询保留原向量排序与关键词回退。追加温湿度和高温字段会使旧索引内容指纹失效，按现有机制重建，未更换嵌入模型。

温室空气湿度参考约60–70%，白天温度约24–27°C；约29.4°C只作为条件性管理参考。昼夜、生育期和设施条件不可省略。日照小时不等于瞬时lux，空气湿度不等于土壤水分。

资料：[UMass / New England Vegetable Management Guide](https://nevegetable.org/crops/tomato-greenhouse-and-high-tunnel)、[University of Maryland Extension](https://www.extension.umd.edu/resource/growing-tomatoes-home-garden)、[Mississippi State University Greenhouse Tomato Handbook](https://extension.msstate.edu/sites/default/files/publications/publications/p1828_web.pdf)。分析链的采纳政策、分歧含义和验证方法见 [S4.md](../S4.md)。
