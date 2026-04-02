# 14_strategic_analysis

**分析日期**: 2026-04-02
**來源**: 3 組調研 Agent + full-review Phase 1 + 技術路線圖分析
**狀態**: 完成（Phase 1-3 full review + 交叉驗證）

---

## 專案現況定位

**介於 portfolio piece 和 research prototype 之間，偏 portfolio piece。**

支持 research prototype 的證據：
- OPA/Rego 用於衛星任務驗證確實無先例（160+ 查詢驗證）
- MCP 介面是太空 MCP 生態中唯一做 workflow 編譯的
- ORCHIDE 互補定位研究扎實（一手資料引用到投影片頁碼）
- 架構設計合理（parse → validate → IR → render 是標準編譯器管線）

支持 portfolio piece 的證據：
- 沒有真實使用者
- 沒有真實任務計劃資料
- execution_mode: parallel 宣稱支援但 renderer 完全沒做
- 核心邏輯 ~670 行，contracts 是純 type stub

## 靜態 YAML 編譯器是否正確

**是，但有到期日。**

- ORCHIDE 自己也是靜態翻譯（slide 23: Custom Translation Layer 是批次式的）
- 衛星任務計劃是提前排定的，靜態編譯符合工作流
- 改成 API server 會膨脹 3-5x 且沒有使用者驗證需求

到期日：需要多衛星協調或即時重規劃時。

## 最大的存在性威脅

**ORCHIDE 2026/05 開源。** 應對策略：
- 監控 orchide-project.eu 和 GitHub
- 如果釋出完整工具 → contribute policy pack + Kueue integration
- 如果只釋出骨架 → 我們是最完整的地面端互補
- 如果什麼都沒釋出 → 我們是唯一開源選項

## v0.2.0 建議聚焦

| 優先 | 項目 | 理由 |
|---|---|---|
| 1 | 實作 parallel execution mode 渲染 | 宣稱有但沒做 = 信譽問題 |
| 2 | 時間線衝突檢測 | 操作者第一天會問的問題 |
| 3 | 找 1 人看 5 分鐘 demo | 沒有使用者驗證 = 所有決策在猜 |
| 4 | 修 4 High findings | 必要衛生 |

## 不做的事

- 不改成 API server
- 不申請 CNCF sandbox
- 不做性能測試
- 不做 OTel integration

## 市場數據（經交叉驗證）

| 市場 | 2025 | 目標年 | CAGR |
|---|---|---|---|
| 衛星地面站 | $41-80B | $246B (2035) | 10-15% |
| 太空 AI 運營 | $2.36B | $15.05B (2034) | 22.9% |
| 地球觀測 | $7.04B | $14.55B (2034) | 8.3% |

## Full Review Phase 1 發現（交叉驗證後修正）

- Critical: 0
- High: 4 (policy stdout/stderr, workflow_name, private import, relative paths)
- Medium: 16
- Low: 8 + 2 (mcp/__init__.py missing, MissionPlan.events empty list)

### 唯一的信譽缺口
`ExecutionMode.PARALLEL` 在 schema 定義、IR 傳遞，但 renderer 零引用 — 所有 DAG 永遠 sequential。

### 交叉驗證修正
- Contract model 數量：21 BaseModel + 1 Enum = 22 classes（非 22 "models"）
- Contract test 數量：37（非報告初始的 34）
- workflow_name 截斷：Argo 直接 sanitize（含 [:63]），Kueue 先 [:50] 再 sanitize — 兩者產出不同名稱

詳見 .full-review/01-quality-architecture.md

## v0.2.0 執行計畫

| 順序 | 任務 | PR scope | 工作量 |
|---|---|---|---|
| 1 | **實作 parallel execution mode 渲染** | renderer 改 DAG 結構 | 2-3 天 |
| 2 | Fix H-1 + H-3: policy.py + sanitize public | 2 quick fixes | 1 小時 |
| 3 | Fix H-2: workflow_name 統一截斷 | compiler refactor | 1 小時 |
| 4 | Fix H-4 + A-6 + #9: eval paths + ResourceHints | IR refactor | 1-2 天 |
| 5 | Fix low: mcp/__init__.py + events min_length | 2 small fixes | 30 分鐘 |
| 6 | Full review Phase 2-5 | security + perf + testing + final | 2-3 天 |
| 7 | Tag v0.2.0 | release | 30 分鐘 |

## 不做的事（經調研確認）

- 不改成 API server（衛星計劃是提前排定的）
- 不申請 CNCF sandbox（專案太小）
- 不做性能測試（3 sample plans 不需要）
- 不做 OTel integration（保持 optional）
- 不做時間線衝突檢測（v0.3.0 範疇）

---

### 更新 (2026-04-02 晚)
- Parallel rendering 已實作（PR #30）— 信譽缺口已修復
- 3 個 High security findings 已修（PR #36, #37）
- Makefile PYTHONPATH 已修（PR #35）
- Docker 支援已完成（PR #29）
