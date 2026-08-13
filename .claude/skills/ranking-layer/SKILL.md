---
name: ranking-layer
description: Ranking Layer 的領域知識 —— 吃多個 bucket list(來自 recall 或 merge),讓開發者指定哪些 bucket 要合併排序,可並行跑多條 merge+sort,輸出多個獨立的 sorted bucket list。architect 設計介面、retrieval-engineer 實作排序策略時載入。
---

# Ranking Layer

## 這一層的目的

吃進多個 Bucket(可以直接來自 Recall Layer,也可以是 Merge/bucket list operation 處理過的),在這裡**指定哪些 bucket 要合併(merge)+ 排序(sort)**,輸出**多個獨立的 sorted Bucket**(sorted BucketList)。這是整個 pipeline 中唯一容許做「精排」的地方(INV-2 的另一面)。

「多條並行」的意思:同一次 search 可能要同時產生不只一組排序結果 —— 例如一組給主結果列表、另一組給「相關但次要」的側欄,兩組用不同的 bucket 組合、不同的排序邏輯,彼此獨立、互不影響。

## 職責邊界

- **必須**明確定義「哪些 bucket 屬於哪一條 ranking pipeline」—— 呼叫端(pipeline orchestrator)要能宣告式指定分組,不要讓 ranking 策略自己去猜該吃哪些 bucket。
- **必須**在輸出時把 `Bucket.sorted` 設成 `True`,且順序即為最終語意上的排序(分數高到低,或依策略定義的排序鍵)。
- **必須**保留來源:一個 sorted bucket 通常是多個輸入 bucket 融合後的結果,`provenance.stage_trace` 要能看出這個 DataPoint 經過了哪些 bucket / 哪個 ranking 策略(INV-3)。
- **不可**吃 `DataPoint.payload` 內部的 source 專屬欄位來排序,除非該欄位已經被對應的 recall 策略正規化成通用欄位(例如統一寫進 `score`)—— 排序邏輯不應該認得「這是論文的 citation count」這種 source 專屬語意,除非明確設計成 source-aware 的排序策略並在文件裡說清楚為什麼。

## 常見排序策略(概念層級,實作由 retrieval-engineer 決定)

- **Score fusion**:多個 bucket 的 `score` 尺度通常不可直接比較(dense 的 cosine 距離、sparse 的 tsquery rank、filter 沒有 score),常見手法:
  - **RRF(Reciprocal Rank Fusion)**:忽略原始分數尺度,只看每個 bucket 內的名次,對每個 DataPoint 算 `Σ 1/(k + rank)`,尺度無關、實作簡單,適合作為第一版 baseline。
  - **加權合併(weighted sum)**:先把各 bucket 的 score 正規化(例如 min-max 或 z-score)到同一區間,再加權相加;需要調權重,較適合有評測數據支撐時再導入。
  - **Learned ranker**:用小型模型(例如 LightGBM / cross-encoder)重新對候選集打分;複雜度高,只在前兩種方法評測數字不夠用時才考慮。
- **Rule-based sort**:直接依某個明確欄位排序(例如純數值 table rows 的場景可能就是「依某欄位大小排序」,不需要語意分數融合)。這種情況通常對應「filter-only」的 bucket,ranking 策略退化成單純排序而非分數融合。

無論選哪種策略,**必須**是可單獨測試的:給定固定的輸入 bucket(內容、score 都是已知的),排序後的輸出應該是可預期、可重現的(不依賴外部即時狀態,除非該策略明確設計成有外部依賴並在文件中聲明)。

## 輸出契約

輸出是 `list[Bucket]`(多個獨立的 sorted bucket,對應多條並行 ranking pipeline),不是單一扁平列表。呼叫端(通常是 business rule 層或 MCP 介面)可以決定要把哪幾個 sorted bucket 用在哪裡,ranking 層本身不決定「這組結果最後要不要被使用者看到」。

## 常見誤區

- 把 recall 階段就有的粗分(例如 pgvector 距離)直接拿來當最終排序分數,不做任何跨策略校正 —— 不同策略的分數尺度不同,直接混用會讓排序結果失真,至少要用 RRF 這種尺度無關的方法起步。
- 在 ranking 策略裡「順手」把某些 DataPoint 濾掉(例如覺得分數太低就丟棄)—— 濾除屬於 recall/merge 階段的職責(拉高 or 收斂候選集),ranking 層預期輸入輸出的 DataPoint 集合基數一致,只改變順序與 score,不做集合縮減(若確實需要 top-K 截斷,那是「排序後的展示層決策」,應該讓呼叫端決定要不要對 sorted bucket 做 slice,而不是藏在排序策略內部悄悄丟資料)。
