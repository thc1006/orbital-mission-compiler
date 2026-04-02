# 13_market_positioning

**調研日期**: 2026 年 4 月 2 日
**來源**: 4 組調研 Agent (160+ 次工具呼叫, 50+ 來源), KubeCon EU 2026 ORCHIDE PDF (36 頁)
**交叉驗證**: 2 組獨立 fact-check Agent 反證測試

---

## 一、本專案是什麼

Satellite Mission Compiler 是一個**地面端任務計劃編譯器**：將結構化衛星任務計劃 (YAML) 編譯為 Argo Workflow / Kubernetes 原生制品，附帶 OPA/Rego 策略驗證和 Kueue 准入語義。

核心功能鏈：
```
Mission Plan YAML → Pydantic Schema Validation → OPA Policy Guard → Workflow Intent IR
  → Argo Workflow Renderer (YAML)
  → Kueue Job Renderer (YAML)
  → MCP Tool Interface (for AI agents)
```

## 二、ORCHIDE 是什麼（基於 KubeCon EU 2026 投影片的一手資料）

### 專案概要
- **全名**: Orchestration of Reliable Computing on Heterogeneous Infrastructures Deployed at the Edge
- **撥款**: EU HORIZON IA #101135595, EUR 2,468,190.81
- **期間**: 2023/12 – 2026/05
- **合作方**: Thales Alenia Space France (協調), Tarides, KP Labs, Thales Romania, Politehnica Bucharest
- **成熟度**: TRL6 (系統原型在相關環境中驗證)
- **開源計畫**: 最後一頁明確宣布將開源

### ORCHIDE 技術堆疊 (來自 PDF 第 15 頁)
| 層級 | 元件 |
|---|---|
| Services Platform (CotS) | Zot Registry, EOS Distributed Storage, Argo Workflow, Vector (Datadog) |
| Specific Services | Mission Manager, Communication Manager, Storage Manager |
| Orchestration | K3S |
| Runtime | containerd, urunc, ukAccel |

### ORCHIDE 硬體目標 (來自 PDF 第 14 頁)
| 節點類型 | 加速器 |
|---|---|
| Nvidia Jetson Xavier/Orin | GPU |
| Versal/Ultrascale SOC FPGA | FPGA |
| ARM64 LX2160 | CPU only |
| MPPA Kalray v2 | Kalray |

### ORCHIDE 的任務計劃 → 工作流翻譯 (來自 PDF 第 23 頁)
ORCHIDE **已實作**「Mission Plan to Argo Workflow translation」:
- 輸入: Priority Queue 中的 Workflow Structure (ID, Trigger time, Priority, Workflow path)
- 處理: Custom Translation Layer (API-wrapper) → Argo Workflows API → K3S API
- 特點: 含 priority-based preemption glue code

### ORCHIDE 的任務計劃格式 (來自 PDF 第 9 頁)
| 欄位 | 說明 | 範例值 |
|---|---|---|
| DATESZ | 日期時間 | 10/06/2029 00:23 |
| ORBIT | 軌道號 | 1 |
| EV | 事件類型 | ACQ, DOWNLOAD |
| DT_EV | 事件持續時間(秒) | 4, 2, 102, 268 |
| INST | 儀器 ID | INST_1 |
| TYPE_D1-D4 | 探測器景觀類型 | O (Ocean), L (Land) |
| VISI | 地面站可見性 | 1 (visible) |
| WORKFLOW_D1-D4 | 工作流 ID | MS (Maritime Surveillance), FD (Fire Detection), CD (Cloud Detection) |
| PRIORITY_D1-D4 | 優先級 (1=最高) | 1, 2, 3 |

## 三、本專案與 ORCHIDE 的精確比較

| 維度 | ORCHIDE | 本專案 |
|---|---|---|
| **執行環境** | 星載 (onboard satellite) | 地面端 (ground-side development) |
| **定位** | 完整星載 PaaS 平台 | 獨立的任務計劃編譯器 |
| **任務計劃→Argo 翻譯** | 有 (嵌入式 glue code) | 有 (獨立 CLI + library) |
| **Policy 驗證** | 無 | OPA/Rego (4 條 deny rules, 可擴充) |
| **Admission 語義** | 無 (custom priority queue) | Kueue (ResourceFlavor, ClusterQueue) |
| **MCP / Agent 介面** | 無 | FastMCP (4 tools) |
| **Golden 測試** | 不明 | 有 (eval_runner + 2 cases) |
| **獨立可用性** | 需要完整 ORCHIDE 平台 | `pip install` + CLI 即可使用 |
| **監控** | Vector + OpenSearch + Prometheus | 設計目標: OTel (尚未實作) |
| **開源狀態** | 即將開源 (KubeCon 宣布) | 已開源 |
| **TRL** | TRL6 | 研究原型 (scaffold) |

## 四、獨特價值 (經交叉驗證確認)

以下四項經 40+ 反證查詢確認在公開領域無先例:

1. **OPA/Rego 用於衛星任務驗證** — ORCHIDE 36 頁投影片零提及 policy/OPA/Rego
2. **Kueue 用於衛星工作負載准入** — ORCHIDE 使用 custom priority queue, 非 Kueue
3. **獨立的任務計劃編譯器** — ORCHIDE 的翻譯層嵌入在 Mission Manager 內部
4. **MCP 暴露任務編譯工具** — 15+ 太空 MCP 伺服器無一做工作流編譯

## 五、競爭風險

### 高風險
- **ORCHIDE 開源後** (預計 2026/05 後), 可能包含可獨立使用的 Mission Plan → Argo 翻譯元件
- **應對**: 差異化在於 policy + admission + MCP + 獨立工具鏈, 而非純翻譯

### 中風險
- **EOEPCA+ 擴展**: ESA 平台可能加入 mission plan 支援 (目前 160 repos 無相關功能)
- **大型營運商自建**: Loft Orbital, Kratos 等可能內部開發類似功能

### 低風險
- 其他太空 MCP 加入工作流產出能力 (目前全部以資料讀取為主)

## 六、市場數據 (經交叉驗證修正)

| 市場 | 2025 | 目標年 | CAGR | 來源 |
|---|---|---|---|---|
| 衛星地面站 | $41-80B | $246B (2035) | 10-15% | SNS Insider, MarketsandMarkets |
| 太空 AI 運營 | $2.36B | $15.05B (2034) | 22.9% | Fortune Business Insights |
| 地球觀測 | $7.04B | $14.55B (2034) | 8.3% | Fortune Business Insights |
| Space as a Service | $6.66B | $17.11B (2034) | 11.5% | Market Research Future |
| 太空雲運算 | $6.12B | $24.94B (2035) | 15.1% | Cervicorn Consulting |

**產業趨勢**: Via Satellite 2026/3/31 報導地面段領導者轉向編排和專業化。

## 七、太空 MCP 生態系統 (經交叉驗證, 共 15+ 個)

| MCP Server | 功能 | 與本專案關係 |
|---|---|---|
| Orbit-MCP | 軌道力學計算 | 互補 (上游資料) |
| IO Aerospace MCP | 星曆/力學 (NAIF SPICE) | 互補 |
| NASA API MCP | 20+ NASA API 存取 | 互補 |
| STK/Ansys MCP | 模擬分析 + 場景建立 | 互補 (STK 可建立場景) |
| SkyFi MCP | 影像存取 + 拍攝下單 | 互補 |
| Copernicus MCP | Sentinel 影像搜尋下載 | 互補 |
| Planetary Computer MCP | 120+ 地理空間資料集 | 互補 |
| Satellite Tracking MCP | 即時衛星追蹤 | 互補 |
| Aerospace MCP | 44+ 航太工具 | 互補 |
| Google Earth Engine MCP | EE 資料查詢視覺化 | 互補 |
| **本專案 MCP** | **任務計劃編譯 + 策略驗證** | **唯一做工作流產出的太空 MCP** |

## 八、學術論文背景

| 論文 | 年份 | 核心貢獻 | 與本專案關係 |
|---|---|---|---|
| KubeSpace (復旦) | 2026 | LEO 衛星 K8s 控制平面, 延遲 -59% | 驗證 K8s 在衛星的可行性 |
| GUIDE (CVPR AI4Space) | 2026 | LLM agent 太空任務決策 | 本專案可作為此類 agent 的基礎設施 |
| DLR Sentinel + Argo | 2021 | Argo Workflows 處理 Sentinel 影像 | 驗證 Argo 在衛星資料處理的可行性 |
| KubeEdge Satellite | 2021 | 精度 +50%, 回傳 -90% | 驗證 K8s 邊緣在衛星的實用價值 |

## 九、建議定位

```
本專案 = ORCHIDE 的地面端互補工具

ORCHIDE 做: 星載 PaaS (K3s + Argo + urunc + ukAccel)
            └── 含嵌入式 Mission Plan → Argo 翻譯 (glue code)

本專案做:   地面端 Mission Plan Compiler
            ├── Schema 驗證 (Pydantic)
            ├── Policy 護欄 (OPA/Rego)     ← ORCHIDE 沒有
            ├── Admission 語義 (Kueue)     ← ORCHIDE 沒有
            ├── 獨立 CLI + Library          ← ORCHIDE 是嵌入式
            └── MCP Agent 介面             ← ORCHIDE 沒有
```

## 十、Repo 檔案更新記錄 (2026-04-02)

| 檔案 | 更新內容 | 狀態 |
|---|---|---|
| `README.md` | 加入 ORCHIDE 互補定位 | 已完成 |
| `CLAUDE.md` | 更新 repo intent, 加入 ORCHIDE 邊界約束 | 已完成 |
| `AGENTS.md` | 更新 repo objective, 加入禁止取代 ORCHIDE 規則 | 已完成 |
| `docs/00_transcript_grounding.md` | 全面改寫, 加入 KubeCon 2026 + D3.1 + D2.2 一手資料 | 已完成 |
| `docs/01_problem_framing.md` | 更新 engineering gap 引用 ORCHIDE D3.1 | 已完成 |
| `docs/04_architecture.md` | 加入 ORCHIDE 關係圖 | 已完成 |
| `docs/05_breakthrough_direction.md` | 更新定位措辭 | 已完成 |
| `docs/08_risks_and_unknowns.md` | 加入 ORCHIDE 開源風險 + 監控差異 | 已完成 |
| `docs/10_agents_and_mcp.md` | 加入太空 MCP 生態定位 | 已完成 |
| `docs/11_research_log.md` | 加入全部調研來源 | 已完成 |
| `.claude/agents/systems-architect.md` | 加入 ORCHIDE 邊界意識 | 已完成 |
| `.claude/agents/researcher.md` | 加入 ORCHIDE 監控職責 | 已完成 |

## 十一、結論

**本專案不是重造輪子。** ORCHIDE 的 mission plan → Argo 翻譯是嵌入式 glue code, 不是可獨立使用的編譯器。本專案的獨特價值在於:
1. **獨立性**: CLI + library, `pip install` 即可用
2. **Policy**: OPA/Rego 策略護欄 (太空領域首例)
3. **Admission**: Kueue 准入語義 (太空領域首例)
4. **Agent-ready**: MCP 介面 (太空 MCP 生態中唯一做工作流編譯的)
5. **可測試性**: Golden evals, TDD 流程, PostToolUse hooks

但必須誠實承認: ORCHIDE 已實作核心翻譯功能, 且即將開源。本專案的護城河在 policy/admission/MCP/獨立工具鏈, 而非翻譯本身。
