# 国家队宽基ETF盘中跟踪（共创项目）

跟踪"国家队"（中央汇金 / 汇金资管 / 诚通 / 国新）通过宽基 ETF 增减仓的**盘中跟踪网站**。数据由 GitHub Actions 每 10 分钟自动抓取，前端在线实时展示，支持朋友协作共创。

在线访问：https://gjd-etf-tracker-89023.app.workbuddy.host/?sharecode=UIM733USUT

---

## 这是什么

- **21 只核心宽基 ETF** 盘中行情：价格 / 涨跌幅 / 成交额 / 换手率 / 量比
- **放量监测**：量比 ≥1.5 放量、≥2 明显放量、成交额 ≥80 亿大额（疑似国家队进场信号）
- **10 分钟累计成交额曲线**：跟踪池合计成交额，盘中每 10 分钟一个点
- **大盘强弱对比**：上证 / 深证 / 创业板 / 科创50 + 涨跌家数
- **国家队持仓基准**：汇金系各机构持仓份额 / 市值 / 占比（2025 年报）
- **份额 / 规模变动**：季度规模环比，反映汇金加减仓方向

> 口径提醒：成交额放大 ≠ 一定是国家队买入（可能是其他大资金），需结合盘面综合判断。

---

## 项目结构

```
gjd-etf-data/
├── README.md                 ← 项目说明 + 协作指南（先看这个）
├── docs/数据源与字段映射.md   ← 数据接口文档 + 踩坑总结（改数据源必看）
├── frontend/index.html       ← 网站前端（单文件，可直接改）
├── config.json               ← ETF 清单 + 国家队持仓基准 + 期货配置（最容易改）
├── fetch_quotes.py           ← 盘中行情 + 10分钟累计成交额抓取（每10分钟）
├── fetch_daily.py            ← 盘后 ETF 份额 / 净流入抓取（每日）
├── gen_intraday_seed.py      ← 生成分时曲线 seed 数据（一次性工具）
├── requirements.txt          ← Python 依赖
├── .github/workflows/        ← 自动抓取定时任务
│   ├── quotes.yml            ← 盘中每10分钟抓行情
│   └── daily.yml             ← 盘后抓份额
└── data/                     ← 自动生成的数据（不要手改，脚本会覆盖）
    ├── quotes.json           ← 行情快照
    ├── intraday.json         ← 10分钟累计成交额曲线
    ├── data.json             ← 份额/净流入
    └── history.json          ← 历史
```

---

## 如何协作（共创指南）

### 第一步：成为协作者

1. 你（仓库所有者）在 GitHub 打开本仓库 → **Settings → Collaborators → Add people**
2. 输入朋友的 GitHub 用户名，邀请
3. 朋友接受邀请后，即可直接推送修改

### 第二步：改哪里

| 想做什么 | 改哪个文件 |
|---|---|
| 加 / 删跟踪的 ETF | `config.json`（`watchlist` 数组）和 `fetch_quotes.py` 顶部的 `ETFS` 列表（保持两者一致） |
| 改放量阈值 / 刷新频率 | `frontend/index.html` 顶部常量（`VR_HOT`/`VR_WARM`/`AMT_BIG`/`REFRESH_MS`） |
| 加数据源 / 改字段 | `fetch_quotes.py` / `fetch_daily.py`，字段映射见 `docs/数据源与字段映射.md` |
| 完善国家队持仓备注 | `config.json` 的 `gjd_note` 字段 + `baseline.holders` |
| 改前端 UI / 加图表 | `frontend/index.html` |

### 第三步：改完推送

```bash
git clone https://github.com/myra956-svg/gjd-etf-data.git
# 改文件后
git add -A
git commit -m "描述你的修改"
git push origin main
```

推送后，GitHub Actions 会自动运行（行情每 10 分钟、份额每日），前端数据随之更新。

---

## 数据刷新机制

| 数据 | 抓取时机 | 脚本 |
|---|---|---|
| 盘中行情 + 10分钟曲线 | 工作日每 10 分钟（UTC `*/10 1-7 * * 1-5` = 北京 9:00-15:59） | `fetch_quotes.py` |
| ETF 份额 / 净流入 | 工作日收盘后 | `fetch_daily.py` |

数据由 GitHub Actions 服务器端抓取 → 写入 `data/` → 前端经 `raw.githubusercontent.com` 跨域读取（公开仓库 raw 支持 CORS，匿名可读）。

---

## 重新部署前端

前端 `frontend/index.html` 改完后，需重新部署才能让在线链接生效（部署动作在 WorkBuddy 里执行）：

1. 在 WorkBuddy 中打开本工作区
2. 对 `frontend/index.html` 所在目录执行部署（`workbuddy_sites_deploy`，static，domainPrefix `gjd-etf-tracker`）

---

## 数据源

全部来自公开接口，免费、无需 token。详细接口地址与字段映射见 [`docs/数据源与字段映射.md`](docs/数据源与字段映射.md)。

- 东方财富（行情 / 均量 / 资金流 / 分时 / 规模）—— 主要数据源
- 同花顺 iFinD、Wind（份额 / 高频数据）—— 辅助，需在 WorkBuddy 会话内调用
