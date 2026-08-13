---
name: search-framework-spec
description: search-framework 專案的核心契約 —— 唯一真相來源。定義 DataPoint / Bucket / BucketList 三個核心詞彙、五層 pipeline 的資料流、五條不變式(INV-1~INV-5),以及 Postgres 作為統一底層儲存的意涵。所有其他 skill 與所有 sub-agent 都以此為準,任何名詞若與本檔衝突,以本檔為準。
---

# search-framework 核心契約

> 這份 skill 對應 `CLAUDE.md` 第 3~4 節,是展開版。改契約先改這裡,再回頭同步 `CLAUDE.md`。兩份文件不得長期不一致。

## 為什麼要有這個框架

上游有多種異質資料源(全球論文、數值 table rows、投影片、機台手冊、先驗知識表),下游只想要「用自然語言查」而不想知道底層是 dense retrieval、sparse retrieval 還是一條 SQL WHERE 子句。這個框架的存在理由就是把這個差異吃掉,對外只暴露一個 MCP `search` 介面。

**設計判準**:任何時候要決定一個東西該放哪一層、該不該加新概念,先問「這樣做,加一個新 data source 或新策略時,是不是還能不改別的 layer?」(INV-5)答不出「是」就代表設計有問題,不要動手。

## 核心詞彙(canonical vocabulary)

這三個詞在整個 codebase **只能有一種定義**,不得在別的地方用同名詞表達不同意思,也不得為同一概念另創別名。

### DataPoint

一個單位的資料 —— 一篇論文、一列 table row、一張投影片、一段機台手冊章節……不管來源是什麼,進了 pipeline 之後一律長這個樣子:

```python
class DataPoint(BaseModel):
    id: str                    # 全域唯一,通常是 f"{source}:{native_id}"
    source: str                # 對應 DataSource 的名字,例如 "arxiv_papers" / "spec_table_rows"
    payload: dict[str, Any]    # source 專屬的實際內容(標題、row 值、投影片文字...)
    score: float | None        # 目前這一步驟給的分數;recall 階段可能是 None 或粗分,ranking 之後一定要有值
    provenance: Provenance     # 見下方,INV-3 要求的可追溯資訊
```

`payload` 是唯一容許「source 專屬結構」滲入的地方,而且**只能出現在 DataPoint 內部**,絕不能讓 `payload` 的內部結構影響到 Bucket / BucketList 層級的操作邏輯(否則就是違反 INV-4)。

### Provenance

```python
class Provenance(BaseModel):
    source: str                  # 同 DataPoint.source,冗餘保留方便單獨追溯
    query_id: str                # 對應 query expansion 產生的哪一條擴增 query
    recall_strategy: str         # 哪個 recall 策略撈出來的(例如 "dense_pgvector" / "sql_filter")
    stage_trace: list[str]       # 依序記錄經過的 stage(expansion -> recall -> merge -> ranking -> business),方便除錯
```

每個 DataPoint 從進 pipeline 到吐出結果,`provenance` 只能「累加」不能「清空重建」—— 每過一層,把該層的資訊 append 進 `stage_trace`,不要整個換掉。

### Bucket

一組 DataPoint 的集合,帶自己的身份:

```python
class Bucket(BaseModel):
    bucket_id: str
    origin: str                  # 產生這個 bucket 的策略名稱(recall 策略 or merge 規則)
    items: list[DataPoint]
    sorted: bool = False         # 這個 bucket 內部順序是否具有「排序」語意(見 INV-2)
```

`sorted=False` 是預設值。只有 ranking 層產出的 bucket 才允許把它設成 `True`;recall 層的策略即使內部用了某種順序(例如 SQL `ORDER BY similarity`)吐出結果,也必須把 `sorted` 標為 `False`,除非該策略明確聲明自己同時扮演 ranking 角色(這種情況非常少見,出現時要在 docstring 特別註明並讓 architect 過目)。

### BucketList

```python
BucketList = list[Bucket]
```

是 recall → merge → ranking 之間傳遞的主要單位。**不是** `list[DataPoint]`,永遠帶著 bucket 的分組與 origin 資訊,直到 ranking 層決定要怎麼合併它們。

## 五層 pipeline 與資料流

```
query (自然語言)
  │
  ▼
[1] Query Expansion Layer   ── 純函數,不接觸資料源
  │  輸出:ExpandedQuery(多條 query variant)
  ▼
[2] Recall Layer            ── 用 sparse / dense / filter 產生多個 Bucket
  │  輸出:BucketList(未精排,sorted=False)
  ▼
[3] Merge(bucket list operation) ── 交集 / 聯集 / top-K,宣告式規則
  │  輸出:BucketList(仍未精排)
  ▼
[4] Ranking Layer           ── 可有多條並行 merge+sort
  │  輸出:多個獨立的 sorted BucketList(每個 bucket.sorted=True)
  ▼
[5] Business Rule Layer     ── 只疊加,不重排/刪改
  │  輸出:最終結果(sorted BucketList + overlay 標記)
  ▼
MCP `search` 回傳給 caller
```

各層詳細契約分別在對應 skill:`query-expansion`、`recall-and-merge`、`ranking-layer`、`business-rule-layer`、`mcp-data-provider`。

## 🔒 五條不變式(INV-1~INV-5)—— 違反即為 bug

這五條是整個專案的紅線,任何 agent(spec-writer / architect / retrieval-engineer / test-engineer)在自己的工作範圍內都要能講出「我這次改動有沒有踩到哪一條」。

- **INV-1** Business Rule Layer 只能「疊加」不能「重排或刪改」ranking 的既有輸出;ranking 結果必須可被獨立還原(拿掉 business rule 這步,剩下的東西要跟 ranking 直接輸出一模一樣)。
- **INV-2** Recall Layer 只負責 recall,**不做最終排序語意**;`Bucket.sorted` 在離開 recall/merge 階段時必須是 `False`。精排一律在 Ranking Layer 發生。
- **INV-3** 每個 DataPoint 從進入管線到輸出都必須保留 `provenance`(來自哪個 source、哪條 query、哪個 recall 策略),`stage_trace` 只能累加。可觀測性靠這個。
- **INV-4** 各層之間只透過 DataPoint / Bucket / BucketList 傳遞,不得傳 source 專屬結構;source 專屬內容只能塞在 `DataPoint.payload` 裡面,不能外溢到其他欄位或成為函式參數。
- **INV-5** 新增/替換一個 data source 或一個 recall 策略,**不得修改** ranking / business rule 層程式。這是可以寫成回歸測試的:新增一個假 source/策略後,其餘層的既有測試應該全數維持通過。

## Postgres 作為統一底層

所有 data source 都落在同一個 PostgreSQL 實例(不同 table / schema),這件事帶來一個關鍵簡化:**dense retrieval、sparse retrieval、結構化 filter,三者都可以表達成 SQL query**。

| 檢索型態 | 典型 Postgres 表達方式 |
|---|---|
| dense retrieval | `pgvector` 的 `<->` / `<=>` 距離運算子,對 embedding column 排序 |
| sparse retrieval | `tsvector` + `tsquery`(`to_tsquery` / `plainto_tsquery`)或 `pg_trgm` 相似度 |
| 結構化 filter(table rows) | 一般 `WHERE` 子句、範圍條件、join |

這代表:

1. 每個 recall 策略在實作層面上都可以只是「一個 SQL 查詢模板 + 參數」,不需要為 dense 另外接一個向量資料庫。細節見 `recall-and-merge` skill。
2. 但**介面層級**(architect 設計的 Protocol)不能因此把「這是 SQL」洩漏成契約的一部分 —— 對 recall 策略的呼叫者(pipeline orchestrator)而言,策略內部用什麼查詢語言是實作細節,呼叫者只認得輸入 `ExpandedQuery` / 輸出 `BucketList`。這樣未來如果某個 source 真的需要換成獨立的向量資料庫,不需要改介面。

## 常見誤區(spec-writer / architect 都要留意)

- 把「業務優先權 item 置頂」寫成「把某個既有 item 移到最前面」—— 這是重排,違反 INV-1。正確語意是「疊加一個新的、優先權更高的 item/bucket 在結果最前面」,原有 ranking 排序不受影響。兩者使用者體感類似,但實作與契約完全不同,spec-writer 寫 spec 時要把這個語意講清楚並讓使用者確認。
- 把 recall 階段的 SQL `ORDER BY` 結果誤當成最終排序 —— 沒有,`Bucket.sorted` 必須是 `False`,下游 ranking 才是精排。
- 為了方便某個 source,在 `payload` 之外的欄位塞 source 專屬資料 —— 違反 INV-4,一律用 `payload`。
