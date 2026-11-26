# oss-radar 设计文档

日期：2026-11-18
状态：已确认（用户口头确认设计定稿）

## 一句话定位

每天定时扫描国内外大厂（Google / Meta / Microsoft / Amazon / Alibaba / Tencent / ByteDance 等）的开源动态，通过 LLM 生成中文技术日报，自动提交回仓库并可选推送摘要。目的是把"每天人工刷仓库、找资料"的过程自动化，为技术分析预研做基础准备。

## 运行环境

- GitHub Actions 每日 cron（北京时间 7:00，即 UTC 23:00），支持手动触发（workflow_dispatch）
- 选择 GitHub Actions 的原因：网络无限制（可自由访问 GitHub API 与海外 LLM API）、免费额度足够、零基础设施

## 整体流程

```
1.发现      2.采集        3.分析         4.产出          5.通知
┌────────┐ ┌─────────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐
│组织列表 │→│新仓库/   │→│LLM 打分   │→│日报 .md    │→│webhook   │
│精选仓库 │ │release/ │ │分类/摘要  │ │archive/   │ │推送摘要   │
│Trending│ │README   │ │(可降级)   │ │state.json │ │(可选)     │
└────────┘ └─────────┘ └──────────┘ └───────────┘ └──────────┘
     ↑ 列表自动维护：Search API 按阈值发现候选，以 PR 形式提交，人工合并生效
                    产出全部 commit 回本仓库
```

## 关键决策

| 维度 | 决策 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | 用户主力语言 |
| 配置方式 | YAML 配置文件驱动 | 用户偏好配置文件优于环境变量；Secrets 仅存放密钥（LLM API Key、webhook URL） |
| LLM | GitHub Models 优先（Action 内置 GITHUB_TOKEN，零配置），Gemini 备选；未配置任何 Key 时自动降级为纯采集模式 | 免费、与 Actions 原生集成 |
| 监控范围 | 三路混合：①组织扫描发现新仓库 ②精选仓库深度跟踪 ③GitHub Trending 交叉过滤 | 兼顾"大厂动态"与"热门趋势" |
| 列表维护 | 自动发现候选（Search API 按 stars/followers 阈值 + LLM 辅助判断是否大厂/是否值得跟踪），以 PR 提交，人工合并生效 | 避免 AI 误判污染列表 |
| 产出 | `reports/YYYY-MM-DD.md` 日报；`archive/` 精选原文；`data/state.json` 增量状态（含 ETag 缓存） | 全部 Git 管理，可追溯历史 |
| 通知 | 飞书 / Server酱 webhook，可选；飞书支持可选签名校验；未配置 URL 则跳过 | 手机看摘要，需要深挖回仓库看全文 |

## 项目结构

```
ossignal/（仓库根）
├── .github/workflows/daily.yml    # 每日 cron + 手动触发
├── config/
│   ├── settings.yaml              # LLM 提供商、阈值、通知开关
│   ├── orgs.yaml                  # 监控组织列表（自动维护）
│   └── repos.yaml                 # 精选仓库列表（自动维护）
├── src/
│   ├── main.py                    # 入口，编排全流程
│   ├── collector.py               # GitHub API 采集（条件请求、限流处理）
│   ├── discover.py                # 列表自动维护（候选发现 → PR）
│   ├── analyzer.py                # LLM 分析（可插拔：github-models / gemini / none）
│   ├── reporter.py                # 日报 Markdown 生成
│   └── notifier.py                # webhook 推送
├── data/state.json                # 增量去重状态（已见过的 repo/release/README 哈希）
├── reports/                       # 日报输出
├── archive/                       # 原始文档归档（README/release notes）
├── requirements.txt
└── README.md
```

## 模块职责与接口

- **collector**：输入 orgs/repos 列表 + state.json，输出"当日值得关注的事件列表"（新仓库、新 release、README 变更、star 激增）。负责 GitHub API 认证、ETag 条件请求、限流退避。
- **discover**：独立运行模式（每周一次或手动）。用 Search API 按阈值找候选组织/仓库，LLM 辅助分类，产出 PR 更新 config/。
- **analyzer**：输入事件列表 + 对应 README/release 文本，输出结构化分析（项目一句话简介、技术分类、推荐理由、亮点摘要）。接口按 provider 抽象，无 Key 时返回原始信息。
- **reporter**：输入分析结果，输出日报 Markdown（按分类组织），并更新 archive/ 与 state.json。
- **notifier**：输入日报摘要，POST 到 webhook。失败不阻塞。
- **main**：编排以上模块，聚合错误，保证单模块失败不中断整体（报告中标注失败项）。

## 数据流细节

1. 加载 config/*.yaml 与 data/state.json
2. 对三个数据源分别采集增量事件（与 state 比对去重）
3. 对值得关注的事件抓取 README / release notes 原文
4. 调 LLM 逐条分析并整体汇总成日报结构
5. 写 reports/YYYY-MM-DD.md、archive/、更新 state.json
6. git commit & push（github-actions bot 身份）
7. 配置了 webhook 则推送摘要

## 错误处理

- GitHub API 限流：ETag 条件请求减少配额消耗；遇到 rate limit 指数退避；单数据源失败跳过并在日报中标注
- LLM 调用失败 / 未配置：降级为"原始信息罗列"模式，日报照常产出
- webhook 失败：仅警告，不影响主流程
- 单仓库采集失败：记录 warning 并继续

## 测试策略

- `python -m src.main --dry-run`：本地干跑，不写文件、不推送、不 commit
- 关键纯函数单测：事件去重、README 哈希、Markdown 渲染、配置加载
- workflow 支持手动触发，方便线上验证

## 明确不做（YAGNI）

- 不做数据库存储（Git 即存储）
- 不做 Web 界面 / 后台管理
- 不做多语言日报（仅中文）
- 不抓取 issues/PRs 内容（仅 release 与 README 层面）
- 不做历史回追（首次运行只记录基线，从第二天开始产出增量日报）
