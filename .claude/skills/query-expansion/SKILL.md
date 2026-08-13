---
name: query-expansion
description: Query Expansion Layer 的領域知識 —— 如何把一條自然語言 query 改寫/擴展成給下游 recall 策略使用的多條 query variant,包含常見策略、輸出契約與職責邊界。architect 設計介面、retrieval-engineer 實作策略時載入。
---

# Query Expansion Layer

## 這一層的目的

輸入一條自然語言 query(或使用者給的關鍵字),輸出「擴增後的查詢集合」—— 多條 query 或多組 keyword,每一條都標明自己是為了給哪一種下游 recall 策略使用。這一層**只重寫/擴展查詢本身**,不查任何資料源、不知道 recall 策略最後怎麼用這些 query。

## 職責邊界

- **必須**是純函數行為:同樣輸入(query + 明確傳入的 context)應該產生語意一致的輸出;**不可**在這一層打 Postgres 或任何 data source ——「不接觸資料源」是 CLAUDE.md 明訂的規則。呼叫 LLM 做 rewrite/paraphrase 是允許的(那是計算,不是資料源存取),但不可以為了「擴展」而去資料庫查同義詞表之類的操作。
- **不可**決定要呼叫哪個 recall 策略,也不可以幫 recall 策略做參數綁定(例如不要在這裡決定 top-K 是多少)——那是 recall 層或 pipeline orchestrator 的事。
- **必須**讓每條擴增後的 query 有自己的 `query_id`,因為 INV-3 要求 DataPoint 的 `provenance.query_id` 能回溯到是哪一條擴增 query 產生的。

## 輸出契約(概念層級,實際型別由 architect 定案)

```python
class QueryVariant(BaseModel):
    query_id: str
    text: str                    # 這一條 variant 的文字
    intent: Literal["dense", "sparse", "filter", "generic"]
    # dense   -> 打算餵給 embedding 模型再做 pgvector 相似度查詢
    # sparse  -> 打算餵給 tsquery / pg_trgm
    # filter  -> 打算被解析成結構化條件(例如數值 table rows 的欄位篩選)
    # generic -> 不特定,由 recall 策略自行決定怎麼用
    weight: float = 1.0          # 這條 variant 相對其他 variant 的重要度,recall/merge 階段可能參考

class ExpandedQuery(BaseModel):
    original_query: str
    variants: list[QueryVariant]
```

`intent` 只是「建議」不是「強制」—— recall 策略可以忽略不符合自己需求的 variant,也可以把 `generic` variant 挪用成任何形式。這一層不強制 recall 策略必須用哪一條。

## 常見策略(由 retrieval-engineer 依需求挑選實作,這裡只列概念)

- **同義詞 / 領域詞擴展**:針對特定 domain(例如機台手冊裡的型號別名)做關鍵字擴展,通常需要一份可維護的詞典,詞典本身不算「資料源查詢」。
- **LLM query rewrite**:把口語 query 改寫成 1~N 條更適合檢索的版本(paraphrase),常見於 dense retrieval 前處理。
- **關鍵字抽取**:從自然語言中抽出適合做 sparse/FTS 的關鍵字組合,對應 `intent="sparse"`。
- **條件抽取(query → structured filter)**:例如「幫我找去年溫度超過 80 度的量測記錄」要拆成「語意部分(可能沒有)」+「結構化條件部分(時間範圍、數值門檻)」,對應 `intent="filter"` 的 variant,通常會是半結構化物件而非純文字(architect 決定這種 variant 的 `text` 該怎麼編碼,例如序列化成 JSON 字串,或擴充 `QueryVariant` 讓 filter 類型帶額外欄位)。
- **HyDE 類技巧(hypothetical document embedding)**:讓 LLM 先生成一段「假想的理想答案」,再把這段文字拿去做 dense embedding —— 這仍然只是「產生一條 dense variant 的文字內容」,沒有違反「不接觸資料源」的邊界。

## 驗收標準怎麼寫(給 spec-writer / test-engineer 參考)

- Given 一條自然語言 query,when 呼叫 expansion,then 輸出至少一條 `intent="generic"` 或以上的 variant(不能空手而回)。
- 每條輸出 variant 的 `query_id` 互不重複。
- 純函數性質可測:同一輸入(含固定的隨機種子/溫度設定,若底層用 LLM)應產生穩定或至少語意等價的輸出 —— 若底層用非確定性 LLM,測試應該驗證「結構契約」(欄位齊全、intent 合法)而非「文字完全相同」。
