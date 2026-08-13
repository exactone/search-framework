---
name: recall-and-merge
description: Recall Layer 與 Merge(bucket list operation)的領域知識 —— 如何用統一的 search 框架讓開發者自訂多種 search 方式產生 bucket list,以及 bucket 之間交集/聯集/top-K 的宣告式規則。涵蓋 dense/sparse/filter 三種檢索在 PostgreSQL 上的統一表達方式。architect 設計介面、retrieval-engineer 實作策略時載入。
---

# Recall Layer + Merge(Bucket List Operation)

## Recall Layer 的目的

用**統一的 search 框架**,讓開發者能自訂義多種 search 方式,各自產生一個或多個 Bucket,目標是**拉高 recall**、不負責精排(INV-2)。多個 recall 策略的輸出合在一起就是一個 `BucketList`。

「統一框架」的意思是:不同 recall 策略(dense / sparse / filter)在**介面**上長得一樣 —— 都是「吃 `ExpandedQuery`(或其中幾條 variant),吐出一個或多個 `Bucket`」,呼叫端不需要知道某個策略底層是不是在打 pgvector。

## Postgres 是所有檢索型態的共同底層

因為資料庫選用 PostgreSQL,dense retrieval、sparse retrieval、結構化 filter 三者都能表達成 SQL,這讓 recall 策略的實作可以高度收斂成「SQL 查詢模板 + 參數綁定」:

| 策略類型 | 適用 data source | SQL 表達 | 備註 |
|---|---|---|---|
| dense | 長文本(論文、投影片圖說、機台手冊章節) | `ORDER BY embedding <=> :query_vector LIMIT :k`(`pgvector`) | 需要先把 query variant 轉成向量(embedding 呼叫發生在策略內部,不算違反「不接觸資料源」—— 那是 expansion 層的邊界,不是 recall 層的) |
| sparse | 標題/內文、投影片標題 | `WHERE to_tsvector('...', content) @@ plainto_tsquery(:kw)` 或 `pg_trgm` 相似度 `similarity(content, :kw) > threshold` | 中文語料通常需要額外的斷詞設定,由 retrieval-engineer 決定用哪個 tsvector config 或第三方斷詞擴充 |
| filter(結構化) | 數值 table rows、先驗知識表 | 一般 `WHERE`、範圍條件、`JOIN` | 通常不需要 embedding,直接用 `QueryVariant(intent="filter")` 解析出的條件組 SQL |

**每個 recall 策略對應一個 Bucket 來源**,`Bucket.origin` 要填策略名稱(例如 `"dense_pgvector_papers"` / `"sql_filter_spec_table"`),方便 INV-3 的 provenance 追溯與之後除錯「這個結果到底是哪個策略撈出來的」。

## 職責邊界

- **必須**只輸出 `BucketList`,`Bucket.sorted` 一律 `False`(即使策略內部用了 `ORDER BY` 或相似度排序,那只是撈資料的手段,不代表最終排序語意 —— INV-2)。
- **不可**在 recall 策略裡做「跨 bucket」的比較或排序決策 —— 一個策略只管自己的 bucket 內容,跨 bucket 的事是 Merge 或 Ranking 的工作。
- **必須**讓新增一個 recall 策略只需要實作策略介面(吃 query variant、吐 bucket),**不需要**碰 merge / ranking / business 層的程式碼(INV-5)。

## Merge(Bucket List Operation)

發生在 recall 之後、ranking 之前,對多個 Bucket 做**集合運算**:

- **交集(intersection)**:兩個以上 bucket 的 DataPoint 若以 `id` 判斷同時出現,才保留 —— 適合「這個 query 同時要滿足語意相關 *and* 某個結構化條件」的場景(例如 dense bucket ∩ filter bucket)。
- **聯集(union)**:多個 bucket 的 DataPoint 去重合併 —— 適合「多種 recall 策略互補拉高 recall」的場景。
- **依某個 index 取 top-K**:在聯集/交集之後,依某個排序鍵(通常是策略給的粗分 `score`,不是最終排序)先截斷,避免下游 ranking 要處理過大的候選集合。**這裡的 top-K 純粹是效能考量,不等於精排**,截斷後的 bucket 仍要標 `sorted=False`。

### 必須是宣告式、可組合的規則

Merge 規則**不可**寫成一次性、內嵌在某個 pipeline 腳本裡的命令式程式碼(例如一串 if/else 硬寫哪個 bucket 跟哪個 bucket 做什麼運算)。要用**可組合的描述**表達,方便之後新增/替換 merge 規則不必改呼叫端邏輯。概念上像這樣(實際型別由 architect 決定):

```python
# 宣告式描述,不是直接執行的程式碼
plan = Intersect(
    Union(bucket("dense_pgvector_papers"), bucket("sparse_fts_papers")),
    bucket("sql_filter_metadata"),
)
plan = TopK(plan, k=50, by="score")
```

這樣的規則本身應該可以被序列化/檢查(至少能印出「這次做了什麼運算」),方便除錯與寫測試 —— 給定固定的輸入 bucket,merge 規則的輸出應該是可預期、可重現的。

## 常見誤區

- 把「dense bucket 內部依 cosine 距離排序」誤當成最終排序拿去用 —— 不行,`sorted` 要是 `False`,而且不同 recall 策略的 score 尺度通常不可比(cosine 距離 vs tsquery rank vs 純 filter 沒有 score),精排融合是 ranking 層的事。
- 在 recall 策略裡直接寫死某個 merge 規則(例如策略內部自己做了聯集)—— 職責混淆,merge 邏輯要獨立在 Merge 這一步,不要塞進單一策略。
- 交集運算時只比對 `payload` 內容而非 `id` —— 不同 source 的 payload 結構不同,交集判斷必須以 `DataPoint.id` 為準(INV-4 的延伸:跨 bucket 操作只認得 DataPoint 的公開欄位)。
