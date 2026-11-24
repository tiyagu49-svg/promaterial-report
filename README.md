# 材智情报：决策者每日简报

当前首页聚焦“可核验的金属行情”。它读取上海期货交易所官方日行情，自动选择成交量最大的主力合约，计算日、周、三个月、同比和 13 周走势。页面不使用参考图中的静态数值，也不会在数据源失败时用演示价格填空。

上期所公开数据属于最近交易日官方收盘数据，不是盘中逐笔报价。稀土、小金属现货及国际行情需要接入拥有展示权限的 SMM、LME 或其他授权服务；未配置时，页面会明确提示并保持缺失状态。

## 启动

```bash
cd multi-agent-platform
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
streamlit run src/mas_platform/web_app.py
```

浏览器默认打开 `http://localhost:8501`。首次加载会读取官方历史数据；之后缓存 5 分钟，也可以点击页面底部“立即刷新”。

## 当前信息架构

- **管理者摘要**：一眼查看领涨、领跌、成交最活跃和已核验品种数。
- **热门金属**：铜、铝、锌、铅、镍、锡、氧化铝、黄金和白银，按业务类别分组。
- **行情主表**：品种/合约、最新价、日、周、3 个月、同比、13 周折线和一句话要点。
- **关注与搜索**：支持“我的关注”与全部品种切换，并按品种或合约搜索。
- **来源详情**：点击任意一行打开价格、成交量、持仓量、趋势、时间戳、计算口径和官方原始链接。
- **实时行业情报**：每分钟可重新检索 Google News RSS，只保留当前自然月的稀土与战略小金属产业文章，去重后按发布时间倒序；消息面与机构观点分栏展示。

官方与授权数据适配器位于 `src/mas_platform/reports/market_feed.py`，数据契约位于 `src/mas_platform/reports/market_intelligence.py`，界面位于 `src/mas_platform/web_app.py`。

原有的文件导入、指标语义和内部经营报告代码仍保留在 `reports/ingestion.py`、`reports/semantics.py` 与 `reports/uploaded.py`，可在第二阶段作为“企业内部数据”能力接入，但不再占据默认首页。

## 生产接入原则

- 价格行情优先使用商业授权 API，确认展示、缓存和再分发权限，不把未授权网页抓取作为核心链路。
- 汇率采用中国外汇交易中心发布的人民币汇率中间价，并记录时间戳与币种口径。
- 政策以商务部、海关总署等官方原文为准，保留原文链接，并对高风险解读设置人工复核。
- 每条情报保留来源、发布时间、影响品种和生成时间；过期或失败的数据源不得伪装成实时数据。
- 新闻发现失败时不回退到历史文章；当前未配置正文分析 API，因此只基于新闻标题识别品种与事件类别，不生成未经正文验证的结论。

## 接入授权现货源

设置 `MAS_MARKET_DATA_URL` 为授权接口 URL 或本地 JSON 文件路径。数据需包含 `source_name`、`source_url`、`as_of`、`mode` 和非空 `quotes`；每条行情需满足 `MarketQuote` 数据契约。系统会把授权现货行情与上期所官方行情合并展示。

```bash
export MAS_MARKET_DATA_URL="https://your-authorised-provider.example/metals.json"
streamlit run src/mas_platform/web_app.py
```

## 验证

```bash
.venv/bin/python -m pytest -q
```

## Streamlit Community Cloud

部署时选择仓库根目录的 `streamlit_app.py` 作为 Main file path。依赖由根目录的
`requirements.txt` 安装；真实密钥只放在 Community Cloud 的 Secrets 设置中，
不要提交 `.env` 或 `.streamlit/secrets.toml`。

行情仅供经营决策参考，不构成交易或投资建议。
