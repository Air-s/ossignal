# oss-radar

每日自动扫描国内外大厂开源动态，LLM 生成中文技术雷达日报，为技术预研做准备。

## 工作原理

1. **采集**（GitHub Actions 每日 07:00 北京时间）：
   - 监控组织（`config/orgs.yaml`）7 天内创建且 star 达标的新仓库
   - 精选仓库（`config/repos.yaml`）的新 release、README 变更、star 激增
   - GitHub 趋势新仓库（Search API 代理）
2. **分析**：LLM 生成中文技术解读（定位/解读/亮点/推荐理由）。**注意：GitHub Models 已于 2026-07-30 全面退役**，请使用 Gemini 或任意 OpenAI 兼容端点（Groq / OpenRouter / DeepSeek 等）；无 Key 时降级为原始信息罗列（明确标注降级）
3. **产出**：`reports/YYYY-MM-DD.md` 日报 + `archive/` 原文归档 + `data/state.json` 增量状态，全部提交回本仓库
4. **通知**（可选）：飞书 / Server酱 webhook 推送摘要

## 快速开始

1. Fork 或 push 本仓库到你的 GitHub 账号
2. 仓库 Settings → Secrets 添加 LLM 密钥（至少一个）：
   - `GEMINI_API_KEY`：Google Gemini（provider 设为 `gemini` 或 `auto` 会自动选用）
   - `OPENAI_API_KEY` + `OPENAI_BASE_URL`（+ 可选 `OPENAI_MODEL`）：任意 OpenAI 兼容端点，如 Groq、OpenRouter、DeepSeek（provider 设为 `openai`）
   - `WEBHOOK_URL`：飞书自定义机器人或 Server酱地址（可选），同时把 `settings.yaml` 的 `notifier.enabled` 改为 `true`
   - `WEBHOOK_SECRET`（可选）：飞书签名校验
3. Actions 页签手动触发 `daily-radar` 验证，首次运行建立基线，次日开始产出增量日报

> LLM provider 决策规则：`provider` 显式指定 `gemini` / `openai` 时走指定 provider；
> `auto`（默认）时优先 Gemini，其次 OpenAI 兼容端点；都没有则降级为纯采集模式。
> 旧的 `github-models` 已退役，不再支持。

## 配置

| 文件 | 说明 |
|------|------|
| `config/orgs.yaml` | 监控组织列表 + 新仓库判定阈值（年龄/star） |
| `config/repos.yaml` | 精选跟踪仓库 |
| `config/settings.yaml` | LLM provider、趋势采集阈值（trending_days/min_stars/limit）、通知开关 |

## 列表自动维护

每周一 06:00（北京时间）`weekly-discover` 自动发现候选组织/仓库，LLM 初筛后以 PR 提交，
你审核合并即生效；不合适的条目删掉再合即可。

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
.\.venv\Scripts\python.exe -m pytest tests/ -v     # 测试
.\.venv\Scripts\python.exe -m src.main --dry-run   # 干跑，不写文件
```
