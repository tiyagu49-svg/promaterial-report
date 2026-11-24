# 材智情报：金属行情决策台

一个面向金属材料、采购和经营决策场景的 Streamlit 数据应用。项目将公开可核验的交易所行情、行业新闻和已有的多智能体分析框架组合起来，提供一个可以直接浏览、检索和追溯数据来源的决策页面。

在线体验：<https://promaterial-report-2xc8a8yki3qyucks73s4yr.streamlit.app/>

代码仓库：<https://github.com/tiyagu49-svg/promaterial-report>

## 项目定位

当前默认首页聚焦“可核验的金属行情”，核心原则是：

- 价格优先来自公开官方接口或已授权的数据服务。
- 每条行情保留来源、原始链接、更新时间和计算口径。
- 数据源不可用时显示缺失或不可用状态，不使用虚构价格补位。
- 新闻模块只做标题级发现和分类；没有正文分析授权时，不把标题信号包装成确定结论。

项目同时保留了一个可扩展的多智能体平台底座，用于后续接入企业内部数据、自动化分析任务和人工复核流程。

## 当前已经实现

### 1. 金属行情仪表盘

- 接入上海期货交易所公开日行情。
- 自动按当日成交量选择主力合约。
- 覆盖铜、铝、锌、铅、镍、锡、氧化铝、黄金和白银等品种。
- 计算日、周、三个月和同比变化，并展示近三个月周度走势。
- 按工业基本金属、新能源与基本金属、战略小金属、贵金属等类别分组。
- 展示领涨、领跌、成交最活跃和行情覆盖等管理者摘要。
- 支持“我的关注”和“全部品种”切换，也支持按品种或合约搜索。

### 2. 数据来源追溯

点击行情表中的品种，可以查看：

- 最新价、最高价、最低价、成交量和持仓量。
- 数据时间、行情状态、交易所和合约。
- 日、周、三个月、同比的计算结果。
- 官方行情页面、原始接口链接和来源说明。
- 可下载的结构化 JSON 字段。

页面会明确区分实时、延迟、官方收盘和快照。当前上期所数据主要是最近交易日官方收盘数据，不是盘中逐笔报价。

### 3. 稀土和战略小金属行业情报

- 通过 Google News RSS 发现当前自然月的相关行业文章。
- 根据稀土、小金属和产业事件关键词筛选内容。
- 过滤部分噪声来源，按标题相似度去重。
- 按“消息面”和“机构观点”分栏展示。
- 自动识别政策、出口、供应、市场、全球布局和风险研判等类别。
- 保留发布时间、媒体来源、原文链接和关联品种。

当前新闻模块是发现和整理层，不负责替代付费数据库、正文级研究或人工判断。

### 4. 可扩展的数据接入

授权的现货行情可以通过 `MAS_MARKET_DATA_URL` 接入。地址可以是 HTTP JSON 接口，也可以是本地 JSON 文件。系统会校验 `MarketFeed` 和 `MarketQuote` 数据契约，再与上期所行情合并展示。

现有的数据分析模块还支持从本地表格中识别日期列、指标列和维度列，并生成周期指标、趋势、分类拆分、异常和驱动因素分析。该能力目前作为底层能力保留，后续可以接入企业内部经营数据页面。

### 5. 多智能体平台底座

项目底层实现了一个面向任务协作的多智能体框架，包含：

- 路由：区分直接请求和需要拆解的复杂目标。
- 规划：生成带依赖关系的子任务，并进行任务协商。
- 调度：按依赖波次执行，独立任务可以并行运行。
- 委派：智能体可以把子任务交给其他专业智能体。
- 记忆：任务结束后写入经验，下一次任务检索相关经验。
- 沙箱：每个智能体拥有独立工作区，跨智能体文件需要显式共享。
- 人在回路：澄清问题和关键工具调用可以请求人工确认。
- 评估：记录任务成功率、子任务数量、耗时、重试和重新规划信息。

这部分目前主要通过 CLI 和内部模块使用，Streamlit 首页暂时以金属行情决策台为主。

## 技术结构

```text
streamlit_app.py                  # Streamlit Community Cloud 入口
src/mas_platform/
├── web_app.py                    # 仪表盘页面与交互
├── reports/
│   ├── market_feed.py            # 上期所与授权现货数据适配
│   ├── market_intelligence.py   # 行情、情报和简报数据模型
│   ├── news_feed.py              # Google News RSS 发现与过滤
│   ├── ingestion.py              # 本地文件导入
│   ├── semantics.py              # 指标语义与聚合规则
│   └── uploaded.py               # 周期报告与上传数据分析
├── agents/                       # 智能体执行循环与注册表
├── orchestration/                # 路由、规划、调度和任务存储
├── core/                         # 事件总线、任务和结果数据结构
├── llm/                          # LLM 客户端与 Mock 客户端
├── memory/                       # 记忆存储、检索和反思
├── sandbox/                      # 智能体工作区隔离
├── human/                        # 人工澄清和审批
└── tools/                        # 工具网关与工具注册
configs/                          # 智能体和系统配置
docs/                             # 架构、接口和评估说明
tests/                            # 单元测试与集成测试目录
```

## 本地搭建

项目要求 Python 3.10 或更高版本。

```bash
cd multi-agent-platform
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

启动 Streamlit 页面：

```bash
streamlit run streamlit_app.py
```

也可以直接启动包内页面：

```bash
streamlit run src/mas_platform/web_app.py
```

浏览器默认访问 <http://localhost:8501>。页面行情缓存约 5 分钟，行业情报缓存约 1 分钟，也可以点击页面底部的“立即刷新”。

## 配置环境变量

复制示例文件后填写真实配置：

```bash
cp .env.example .env
```

主要配置项如下：

```bash
# LLM 配置，仅在使用多智能体能力时需要
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=your-key-here
LLM_MODEL=deepseek-chat

# 可选：授权现货数据接口或本地 JSON 文件
MAS_MARKET_DATA_URL=https://your-authorised-provider.example/metals.json

# 可选：无网络开发和测试
LLM_PROVIDER=mock
```

不要把真实密钥提交到 GitHub。`.env`、`.streamlit/secrets.toml`、虚拟环境、缓存和运行时数据已经在 `.gitignore` 中排除。部署到 Streamlit Community Cloud 时，把密钥放到应用的 Secrets 设置中。

授权现货 JSON 至少应包含以下字段：

```json
{
  "source_name": "授权数据源",
  "source_url": "https://example.com/market-data",
  "as_of": "2026-11-24T15:00:00+08:00",
  "mode": "live",
  "quotes": []
}
```

`quotes` 中的每条记录需要符合 `MarketQuote` 数据模型，包括品种、价格、单位、变化率、来源和更新时间等字段。

## 使用 CLI 多智能体平台

安装项目后可以使用 `mas` 命令：

```bash
mas chat
mas chat --dm coder
```

系统配置在 `configs/system.yaml`，智能体配置在 `configs/agents.yaml`。如果只想运行离线测试，可以使用 Mock LLM 配置，不需要真实 API Key。

## 测试与验证

运行全部单元测试：

```bash
python -m pytest -q
```

只运行市场数据和新闻模块测试：

```bash
python -m pytest -q tests/unit/test_market_feed.py tests/unit/test_market_intelligence.py tests/unit/test_news_feed.py
```

测试重点包括数据契约校验、主力合约选择、变化率计算、新闻筛选去重、报告聚合和多智能体调度。

## Streamlit Community Cloud 部署

1. 将仓库连接到 Streamlit Community Cloud。
2. 选择仓库 `tiyagu49-svg/promaterial-report`。
3. 选择 `main` 分支。
4. 将 Main file path 设置为 `streamlit_app.py`。
5. 确认根目录的 `requirements.txt` 会被安装。
6. 在 Advanced settings 或 Secrets 中配置需要的环境变量。

部署入口 `streamlit_app.py` 会自动把 `src` 加入 Python 模块路径，再调用 `mas_platform.web_app.main()`。

## 当前限制

- 上期所公开接口主要提供最近交易日官方收盘数据，不等同于实时行情。
- 稀土、小金属现货和国际基准价尚未默认接入商业授权 API。
- 新闻内容来自 Google News RSS 的发现索引，当前没有正文级 AI 摘要。
- 页面运行依赖外部数据源；数据源不可用时，页面会保留明确的缺失状态。
- 多智能体平台已经具备核心调度能力，但还没有和首页的行情、新闻、报告工作流完全打通。

## 后续优化方向

### 数据和合规

1. 接入获得展示和再分发授权的 SMM、LME 或其他商业数据服务。
2. 增加数据源健康检查、失败重试、断路器和数据新鲜度监控。
3. 建立统一的数据版本、时间戳和审计记录，支持结果回溯。
4. 对政策、出口和供应链内容增加官方原文优先级和人工复核状态。

### 分析能力

1. 将现货、期货、汇率、库存和进出口数据放入同一套标准化数据模型。
2. 增加基差、期限结构、库存变化、波动率和异常行情指标。
3. 将标题级情报升级为授权正文解析，并保留证据片段和引用关系。
4. 支持用户保存关注组合、阈值提醒和定时日报。

### 产品和工程

1. 将 Streamlit 页面拆分为数据层、分析层和展示层，降低页面文件复杂度。
2. 增加类型检查、格式化、静态检查和 CI，在每次提交时自动运行测试。
3. 补充端到端测试，覆盖外部接口失败、空数据和字段变更场景。
4. 为多智能体平台增加可视化运行轨迹、任务重试记录和人工审批面板。
5. 增加权限、密钥轮换、请求限流和缓存策略，满足长期公开部署要求。

## 目录说明

- `docs/architecture.md`：多智能体系统架构。
- `docs/interfaces.md`：模块接口和数据契约说明。
- `docs/evaluation_protocol.md`：评估协议。
- `configs/agents.yaml`：智能体角色、工具和权限配置。
- `configs/system.yaml`：运行时、模型、记忆和编排配置。
- `examples/demo_daily_data.json`：本地数据分析示例。

行情和情报仅供经营决策参考，不构成交易或投资建议。

