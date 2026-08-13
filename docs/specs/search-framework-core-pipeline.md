# Spec: search-framework 核心 pipeline(query expansion → recall → merge → ranking → business rule)

## 背景

使用者要建立一個 search framework,目的是在多種異質 document type(PDF/PPTX 的 chunks、table rows)前面提供統一的邏輯層。搜尋輸入是自然語言,背後可能對應 dense retrieval、sparse retrieval 或 SQL query;因為資料庫選用 PostgreSQL,dense 與 sparse retrieval 也都能用 SQL 表達。

使用者描述的 high level 框架(原文用詞保留於此,canonical 對應見下方「涉及範圍」與各條需求):

- **query expansion**:重寫 query,或擴展 keyword。
- **recall layer**:目標是提高 recall,用統一的 search 框架讓開發者自訂多種 search 方式,篩選出多個 bucket(a list of bucket,簡稱 bucket list)。
- **bucket list operation**(對應 CLAUDE.md 的「Merge」):進 ranking layer 之前,對多個 bucket 做交集、聯集,或依某種 index 取 top-K。
- **ranking layer**:吃多個 bucket list(直接來自 recall 或 bucket list operation),可指定哪些 bucket 要 merge + rank,輸出獨立的幾個 sorted bucket list。
- **business rule layer**:依業務邏輯,額外附加 bucket list,或放上業務上優先權更高的 item(例如全球熱搜)。

這份 spec 是專案初始的整體架構 spec,對應 CLAUDE.md 第 4 節已定義的五層 pipeline 與 INV-1~INV-5 不變式 —— 使用者的口語描述與既有 CLAUDE.md 高度一致,本 spec 的任務是把它定型為可驗收的規格,而不是重新設計。

## 涉及範圍

- **Pipeline layer**:跨層(query expansion / recall / merge / ranking / business rule 全部涵蓋,這是初始整體架構 spec)。
- **Data source**:沿用 CLAUDE.md 第 2 節既有清單 —— 全球論文、純數值 table rows、投影片、機台手冊、各單位先驗知識表。使用者這次提到的「PDF/PPTX chunks、table rows」對應到既有清單中的子集,詳細映射見「待確認事項」。不新增資料源。
- **是否觸碰 app/core/**:**是**。`DataPoint`、`Bucket`、`BucketList`、`Provenance` 等核心型別,以及五個 layer 的介面(Protocol/ABC),目前完全不存在(`app/` 目錄尚未建立),本 spec 涵蓋的每一條需求都需要 architect 先行設計。

## 功能需求

**Query Expansion**

1. 系統必須接受一條自然語言 query(或關鍵字)作為輸入,輸出一組擴增後的 query variant(`ExpandedQuery`),每條 variant 標記其用途意圖(dense / sparse / filter / generic)。
2. 系統不可在 query expansion 階段存取任何 data source(純函數邊界,不得查 Postgres 或其他外部資料源)。
3. 每條輸出的 query variant 必須帶有唯一 `query_id`,供下游 `DataPoint.provenance` 回溯。

**Recall**

4. 系統必須提供統一的 recall 策略介面,讓開發者可自訂多種 search 方式(dense retrieval / sparse retrieval / SQL 條件 filter),每種方式各自實作為一個獨立、可單獨測試的策略。
5. 因資料庫為 PostgreSQL,系統必須讓 dense、sparse、filter 三種檢索型態都能以 SQL 表達(dense 用 pgvector 距離運算子、sparse 用 tsvector/tsquery 或 pg_trgm、filter 用一般 WHERE 條件),但此實作事實不可外洩到 recall 策略的對外介面 —— 呼叫端不應該需要知道底層是不是 SQL。
6. 每個 recall 策略的輸出必須是一個或多個 `Bucket`,合併起來構成 `BucketList`;`Bucket.sorted` 必須為 `False`(即使策略內部用了排序手段撈資料)。
7. 系統必須讓新增一個 recall 策略時,不需修改 merge / ranking / business rule 層的既有程式碼。

**Merge(Bucket List Operation)**

8. 系統必須提供對多個 `Bucket` 做「交集」「聯集」「依某個 index(如 score)取 top-K」三種操作,且這些操作規則必須是宣告式、可組合描述的,不得寫死成單一 pipeline 腳本裡的命令式邏輯。
9. Merge 產出的 `Bucket` 同樣不得帶有最終排序語意(`sorted` 仍為 `False`)。

**Ranking**

10. 系統必須讓 ranking 階段能吃多個 `Bucket`(不論直接來自 recall 或經過 merge),並讓呼叫端能指定「哪些 bucket 要合併排序成一組」。
11. 系統必須支援多條並行的 merge+rank pipeline,彼此獨立,各自輸出一個獨立的 sorted `BucketList`。
12. Ranking 輸出的每個 `Bucket` 必須標記 `sorted=True`,且 bucket 內順序即代表最終排序語意。

**Business Rule**

13. 系統必須讓業務邏輯能疊加額外的 `Bucket`,或插入業務優先權更高的 item(例如全球熱搜)到既有 ranking 結果上。
14. 系統不可讓 business rule 層重新排序、刪除或修改既有 ranking 輸出中原本存在的 item 順序(INV-1);business rule 的輸出必須能被拆解回「原始 ranking 輸出」與「疊加內容」兩部分。

**跨層**

15. 系統必須讓每個 `DataPoint` 從進入 pipeline 到最終輸出,持續攜帶 `provenance`(source、擴增後的 `query_id`、recall 策略名稱),並在經過各層時累加 `stage_trace`,不得清空重建。
16. 各層之間只能透過 `DataPoint` / `Bucket` / `BucketList` 三種型別傳遞資料,不得傳遞任何 source 專屬結構;source 專屬內容一律收斂在 `DataPoint.payload` 內。

## 驗收標準(Acceptance Criteria)

- [ ] Given 一條自然語言 query,when 呼叫 query expansion,then 輸出至少一條 query variant,且每條都有唯一 `query_id` 與合法的 intent 標記(dense/sparse/filter/generic)。
- [ ] Given query expansion 執行過程,when 觀察其對外行為,then 不應觀察到任何對 Postgres 或其他 data source 的存取。
- [ ] Given 至少兩個不同的 recall 策略(例如一個 dense、一個 filter)註冊在同一個 recall layer,when 對同一條 `ExpandedQuery` 執行 recall,then 輸出的 `BucketList` 包含來自兩個策略各自產生、`origin` 標記正確的 `Bucket`,且每個 `Bucket.sorted` 為 `False`。
- [ ] Given 兩個 `Bucket`(來自不同 recall 策略),when 對它們套用交集 merge 規則,then 輸出的 `Bucket` 只包含兩者 `DataPoint.id` 皆存在的項目,且輸出 `Bucket.sorted` 仍為 `False`。
- [ ] Given 兩個 `Bucket`,when 對它們套用聯集 merge 規則,then 輸出的 `Bucket` 包含兩者所有 `DataPoint`(依 `id` 去重),不遺漏、不重複。
- [ ] Given 一個 merge 後的 `BucketList`,when 套用「依 score 取 top-K」規則(K=10),then 輸出 `Bucket` 的 item 數不超過 10,且是原集合中 score 最高的前 10 筆。
- [ ] Given 多個 `Bucket`(部分來自 recall、部分來自 merge),when 呼叫 ranking 並指定其中某幾個 bucket 為一組,then 只有被指定的 bucket 參與這組排序,輸出為一個 `sorted=True` 的 `Bucket`,未被指定的 bucket 不受影響。
- [ ] Given 同一次呼叫指定兩組不同的 bucket 組合分別做 ranking,when 執行,then 輸出兩個獨立的 sorted `Bucket`,彼此排序結果互不影響。
- [ ] Given 一個 sorted `BucketList`(來自 ranking)與一條「插入全球熱搜 item 到最前面」的業務規則,when 執行 business rule 層,then 輸出結果去除疊加部分後,與原始 sorted `BucketList` 逐項比對完全相等(驗證 INV-1 可還原性)。
- [ ] Given 一個 `DataPoint` 從 recall 產生、經過 merge、ranking、business rule 四層,when 檢查其 `provenance`,then `source`、`query_id`、`recall_strategy` 皆非空,且 `stage_trace` 依序包含四層各自留下的紀錄,無任何一層清空前面的紀錄。
- [ ] Given 新增一個假的 data source 與對應 recall 策略(不修改既有 ranking / business rule / merge 程式碼),when 執行既有的 ranking / business rule / merge 層測試,then 全數維持通過(驗證 INV-5)。

## 不變式檢查

- **INV-1**(business rule 只疊加不重排):相容。需求 13/14 明確要求只能疊加並可還原,對應驗收標準直接測這條。若未來出現「把既有 item 排到第一名」這類需求,語意上是重排,不屬於 business rule 層,需另外走 ranking 層加權 —— 這次 spec 沒有這類需求。
- **INV-2**(recall 不做精排):相容。需求 6/9 明確要求 recall 與 merge 輸出的 `Bucket.sorted` 皆為 `False`,精排限定在 ranking 層(需求 10~12)。
- **INV-3**(provenance 保留):相容。需求 3、15 明確要求 `query_id` 與 `provenance`/`stage_trace` 全程保留、只能累加。
- **INV-4**(跨層只用 DataPoint/Bucket/BucketList):相容。需求 16 明確要求跨層只用三個核心型別,source 專屬內容收斂在 `payload`。
- **INV-5**(新增 source/策略不改動其他層):相容。需求 7 明確要求新增 recall 策略不動其他層;驗收標準最後一條直接測這件事。

## 交接

- 下一步交給:**architect**
- 原因:本 spec 每一條需求都要先建立 `app/core/` 的核心型別(`DataPoint`/`Bucket`/`BucketList`/`Provenance`)與五個 layer 的介面(Protocol),目前 `app/core/` 完全不存在,屬於初始骨架設計。依專案規範,任何觸碰 `app/core/` 的工作都要先交給 architect,不能讓 retrieval-engineer 直接動手猜介面形狀。

## 建議的驗收測試(給 test-engineer,待 architect 定案介面後執行)

- 五個 layer 各自的單元測試(給定固定 input bucket/query,驗證輸出符合上方驗收標準)。
- INV-1 回歸測試(business rule 可還原性)—— 專案紅線,優先度最高。
- INV-5 回歸測試(新增假 source/策略後,其餘層測試全數通過)。
- 至少一個端到端 demo use case:一條自然語言 query 進去,經過完整五層,到最終輸出(尚不需要接 MCP,可先在 pipeline 層級驗證)。

## 待確認事項

- CLAUDE.md 第 2 節資料源清單是「全球論文」「純數值 table rows」「投影片」「機台手冊」「先驗知識表」。使用者這次提到「PDF 或 PPTX 的 chunks,或是 table rows」——PPTX 可對應「投影片」,table rows 可對應「純數值 table rows」,但「PDF chunks」對應「全球論文」還是「機台手冊」(或兩者皆是,只是切 chunk 方式不同)不確定,需要使用者確認,會影響 architect 之後設計 `DataSource` adapter 時是否要區分兩種 PDF 語意。
- 「bucket list operation」中「依某種 index 取 top-K」的 index 具體指什麼排序鍵 —— 目前 spec 假設是策略給的粗分 `score`,若有其他排序鍵(例如時間)需求,要另外列出。
- Ranking 層「指定哪些 bucket 要 merge+rank」的指定方式,是由呼叫 MCP `search` 的 caller 動態決定,還是由開發者在 pipeline 設定檔裡預先寫死分組規則?這會影響 architect 設計介面時,這個參數要不要暴露到 MCP tool schema。目前 spec 未指定,建議 architect 先假設為「內部設定,不對 MCP caller 暴露」,除非使用者確認需要動態指定。
- Business rule 層「業務上優先權更高的 item」除了全球熱搜,是否還有其他已知類型(例如廣告/贊助內容)?若有,是否需要額外稽核欄位(例如 `reason`/來源)——目前沿用 skill `business-rule-layer` 建議的 `OverlayItem.reason` 設計,但尚未得到使用者明確確認是否要在這階段定案。
