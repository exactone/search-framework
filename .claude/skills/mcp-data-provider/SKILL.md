---
name: mcp-data-provider
description: MCP data provider 介面設計知識 —— 如何把整條 search pipeline 對外暴露成單一 MCP `search` tool,包含 input schema 設計、對 LLM 友善的 tool description 撰寫、回傳格式取捨。architect 設計 MCP 介面骨架時載入。
---

# MCP Data Provider

## 這一層的目的

把 Query Expansion → Recall → Merge → Ranking → Business Rule 整條 pipeline,對外收斂成**一個** MCP `search` tool。上游 caller(其他 MCP client / agent)只看到這一個介面,看不到底層資料源差異、也看不到內部的 layer 切分。

## Input schema 設計原則

- **必須**以自然語言 query 為主要輸入,不得把 source 專屬參數洩漏到 input schema(例如不該出現 `pgvector_top_k` 這種只有 dense 策略才懂的參數)。若真的需要暴露一些通用控制項,要以「使用者/caller 語意」命名,而不是「實作語意」命名 —— 例如用 `max_results` 而不是 `limit_per_bucket`。
- 可以有**選擇性**的結構化 filter 參數(例如時間範圍、來源類型),但要設計成通用形狀,能被對應到 Recall Layer 的 filter 策略,而不是為特定 source 開的後門。
- 依使用者個人慣例(見專案根目錄外的個人 CLAUDE.md):MCP tool 的 description 要清楚寫給 LLM 看,視為對外 API 文件的一部分 —— 這不是 nice-to-have,是必須項。description 要講清楚:
  - 這個 tool 什麼時候該被呼叫(例如「當使用者想查詢論文、投影片、量測數據或設備手冊內容時使用」)。
  - 輸入參數的語意與限制(例如 query 是否支援中英混合、filter 的格式)。
  - 輸出的形狀與意義(不是只寫型別,要講「這代表什麼」)。

## 回傳格式

- **必須**回傳 `DataPoint`(或其精簡投影),**不可**把內部的 `Bucket` / `BucketList` 結構直接暴露成 MCP 回傳格式,除非有明確理由(例如 caller 明確需要知道分組資訊)且已經跟使用者確認。多數情況下 caller 只關心「一個排序好的結果列表」,不需要知道內部經過幾個 bucket、怎麼 merge 的。
- 精簡投影時,`provenance` 是否要對外暴露要看場景 —— 內部除錯很需要,但對外 MCP 回傳通常只需要保留「來源類型」這種粗粒度資訊(例如 `source: "arxiv_papers"`),不必把 `stage_trace` 這種內部細節整包吐給 caller,除非 caller 明確是開發/除錯用途。
- Business Rule Layer 疊加的內容與 ranking 原始結果,對外回傳時是否要區分(例如標記哪些 item 是「熱搜插入」)要看業務需求 —— 若需要區分,對應到 `OverlayItem.reason` 之類欄位可以選擇性透出。

## 職責邊界(architect)

- 這裡**只設計 tool schema**(input schema、output schema、description),不寫 pipeline 的實際串接邏輯與各層策略 —— 那是 retrieval-engineer 依 architect 訂出的介面契約去實作。
- Tool schema 的設計要能在不改變 schema 本身的前提下,讓底層新增 data source / recall 策略(INV-5 的 MCP 層版本):如果新增一個 data source 導致 input/output schema 必須跟著改,代表 schema 設計把底層細節洩漏出來了,要重新檢視。

## 副作用與授權(個人慣例延伸)

- `search` 本身是唯讀查詢,一般不涉及副作用,不需要授權確認流程。
- 若未來這個 MCP server 要加入其他有副作用的 tool(例如寫入使用者回饋、更新業務優先權清單),依使用者個人 CLAUDE.md 慣例:「對外部系統(DB、API)有副作用的 tool,預設視為需要授權確認的操作,除非使用者已明確說可以自動執行」—— 這類 tool 的 schema 設計要把這個限制在 description 中講清楚,並在實作時走確認流程,不要跟 `search` 這種唯讀 tool 混在同一份骨架裡討論。
