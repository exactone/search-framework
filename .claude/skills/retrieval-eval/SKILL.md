---
name: retrieval-eval
description: 檢索評測方法論 —— recall@k / precision@k / NDCG@k 的定義與計算、golden dataset 格式、baseline vs 改動後對比報告格式。test-engineer 撰寫評測腳本、驗證任何影響檢索行為的改動時載入。
---

# Retrieval Evaluation(recall@k / precision@k / NDCG@k)

## 為什麼需要這個

CLAUDE.md 第 8 節規定:「檢索行為的改動必須附評測數字(至少 recall@k 前後對比),不接受『感覺變好』。」這份 skill 定義評測怎麼做、數字怎麼算、golden dataset 怎麼存,確保不同測試對同一個指標算出一致的數字。

## 指標定義

給定一條 query,`relevant` = golden dataset 標註的相關 DataPoint id 集合,`retrieved@k` = pipeline 對這條 query 回傳的前 k 個 DataPoint id(依最終排序取前 k)。

- **recall@k** = `|retrieved@k ∩ relevant| / |relevant|` —— 前 k 個結果裡,撈回了多少比例的「應該要找到的東西」。這是 Recall Layer 最直接對應的指標,但**整條 pipeline 端到端也要測**,因為 merge/ranking 的 top-K 截斷也會影響最終 recall@k。
- **precision@k** = `|retrieved@k ∩ relevant| / k` —— 前 k 個結果裡有多少比例是真正相關的,對應 Ranking Layer 排序品質。
- **NDCG@k(Normalized Discounted Cumulative Gain)**:若 golden dataset 有分級相關度(不是只有「相關/不相關」二元,而是 0~n 分),用這個指標衡量「越相關的 item 排越前面」的品質。計算方式:
  1. `DCG@k = Σ_{i=1}^{k} rel_i / log2(i + 1)`(`rel_i` 是第 i 個結果的相關度分數,`i` 從 1 起算)
  2. `IDCG@k` = 同一組相關度分數依「理想排序」(分數由高到低)算出的 DCG@k
  3. `NDCG@k = DCG@k / IDCG@k`

三個指標只寫**一份共用實作**,放在 `tests/eval/metrics.py`(或等效位置),所有評測腳本都呼叫同一份,不得各自重寫一次計算邏輯 —— 這是避免「不同測試對同一指標算出不同數字」的唯一方法。

## Golden Dataset 格式

存放在 `tests/eval/golden/`,建議用 JSONL,每行一條 query 的標註:

```json
{
  "query_id": "q001",
  "query": "去年溫度超過 80 度的量測記錄",
  "relevant": [
    {"id": "spec_table_rows:12345", "grade": 3},
    {"id": "spec_table_rows:12399", "grade": 2}
  ],
  "notes": "grade: 3=高度相關 2=部分相關 1=勉強相關 0/未列出=不相關",
  "labeled_by": "someone@example.com",
  "labeled_at": "2026-08-01"
}
```

- **必須**註明資料來源與標註方式(人工標註 / 從既有系統的點擊資料回填 / LLM 輔助標註後人工覆核……),方便之後追加或稽核。
- **必須**版本化 —— golden dataset 改動(增刪 query、改標註)要能追溯到是哪個版本,評測報告要註明用的是哪個版本/大小(見下方報告格式),避免「數字進步了,但其實是換了一份更簡單的 dataset」這種誤導。
- 若標註只有二元相關/不相關,`grade` 可省略或固定填 1,NDCG 仍可計算(退化成 binary relevance 版本)。

## 評測報告格式

每次針對「影響檢索行為的改動」(recall 策略、ranking 策略、merge 規則、business rule 規則)提供評測報告,**必須**包含:

```markdown
## 評測報告:<改動描述>

- Golden dataset:`tests/eval/golden/v3.jsonl`(N=42 queries)
- k = 10(或視情境列出多個 k,例如 5/10/20)

| 指標 | Baseline(改動前) | 改動後 | 差異 |
|---|---|---|---|
| recall@10 | 0.71 | 0.78 | +0.07 |
| precision@10 | 0.55 | 0.60 | +0.05 |
| NDCG@10 | 0.66 | 0.71 | +0.05 |

結論:<一句話,例如「新增 sparse fallback 策略後,對長尾 query 的 recall 提升明顯,無 precision 退步」>
```

沒有 baseline 數字對比,一律不算完成 —— 即使只是「感覺這樣改比較合理」也要先跑一次評測拿到實際數字再下結論。

## 常見誤區

- 為了讓測試好過,把 recall@k 的門檻設得很低 —— 門檻要對應 spec 裡的驗收標準或使用者明確要求,抓不到門檻就先問使用者,不要自己拍板。
- 用 mock 掉整個 recall/ranking 邏輯來測「端到端 demo use case」—— mock 適合單元測試裡隔離單一 data source 的外部依賴(例如 mock 掉某個慢速 API),但整合測試/評測要驗證真實的層間串接,否則數字沒有意義。
- golden dataset 只包含「容易的」query,沒有涵蓋長尾/邊界情境 —— 這樣 recall@k 數字會虛高,對真實使用情境沒有代表性,標註時要刻意涵蓋難的案例。
