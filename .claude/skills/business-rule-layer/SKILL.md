---
name: business-rule-layer
description: Business Rule Layer(算法補充層)的領域知識 —— 根據業務邏輯疊加 bucket list 或插入高優先權 item(例如全球熱搜)。核心是 INV-1(只能疊加,不能重排或刪改 ranking 輸出)。architect 設計介面、retrieval-engineer 實作規則、test-engineer 寫回歸測試時載入。
---

# Business Rule Layer(算法補充層)

## 這一層的目的

根據業務邏輯,在**不改動 ranking 輸出**的前提下,額外附加 bucket list,或把業務上優先權更高的 item(例如全球熱搜、營運指定內容)疊加/插入到結果上。這是整條 pipeline 裡**唯一**容許「業務邏輯」介入排序結果外觀的地方,但代價是它被 INV-1 嚴格限制住能做什麼。

## INV-1 是這一層唯一重要的事

> Business Rule Layer 只能「疊加」不能「重排或刪改」ranking 的既有輸出;ranking 結果必須可被獨立還原。

**判斷方法**:寫完一個 business rule 之後,自問「如果把這個規則整個拿掉,剩下的結果是不是跟 ranking 層直接輸出的東西完全一樣、可以被還原?」答不出「是」就是違反 INV-1。

### 什麼是「疊加」、什麼是「重排」——這是最容易混淆的地方

- ✅ **疊加**:在結果最前面插入一個新的 item/bucket(這個 item 原本可能根本不在 ranking 的候選集合裡,或者是從別的來源直接指定的)。原本 ranking 產出的 sorted bucket 內部順序完全不動。
- ✅ **疊加**:額外附加一個全新的 bucket(例如「熱門推薦」獨立於主結果之外顯示),不動主結果 bucket。
- ❌ **重排(禁止)**:把 ranking 結果裡「原本排第 15 名的 item」移動到第 1 名 —— 即使業務理由聽起來很像「置頂」,只要是「移動既有 item 的位置」,語意上就是重排,違反 INV-1。
- ❌ **刪改(禁止)**:因為業務理由把 ranking 結果裡的某個 item 拿掉,或改動它的 score/順序。

**如果業務需求真的是「讓某個既有 item 的排序名次提升」**(不是插入新 item,而是要動既有 item 的位置),那個需求**不屬於 business rule layer**,語意上應該回頭表達成 ranking 層的加權(例如「這個 item 的業務權重加分」變成 ranking 融合分數的一個輸入項)。spec-writer 在寫 spec 階段就要把這種需求攔下來,說明「這其實是 ranking 層的加權需求,不是 business rule 層的疊加需求」,並在 spec 的不變式檢查表裡標記衝突與替代方案,而不是默默放行讓 retrieval-engineer 硬做出違反 INV-1 的實作。

## 實作模式:唯讀輸入、疊加輸出

輸入的 sorted BucketList 視為**唯讀**,不可 in-place 修改、刪除或重新排序。輸出是「疊加後的新結果」,概念上像是:

```python
class OverlayResult(BaseModel):
    base: list[Bucket]          # 原封不動的 ranking 輸出,完全可還原
    overlays: list[OverlayItem] # 疊加的內容,各自標明插入位置語意(例如 "pin_top" / "inject_bucket")

class OverlayItem(BaseModel):
    bucket_or_datapoint: Bucket | DataPoint
    placement: Literal["pin_top", "append_bucket", "inline_at"]
    reason: str                  # 業務理由,方便之後稽核(例如 "global_trending" / "sponsored")
```

具體資料結構由 architect 決定,但關鍵設計原則是:**型別上就要讓「base」與「overlay」分離**,不要把兩者攤平合併成單一 list 才輸出 —— 攤平之後就無法程式化驗證可還原性,只能靠人工 review,容易在之後的修改中不小心破壞 INV-1 而沒人發現。

## 常見業務規則(概念層級)

- **全球熱搜插入**:與使用者這次 query 語意未必相關,但業務上想曝光,通常對應 `placement="pin_top"` 或 `"append_bucket"`。
- **贊助 / 廣告內容**:類似熱搜插入,但通常需要額外的 `reason` 稽核欄位(合規需求)。
- **黑名單過濾**:如果業務要求「某些 item 不能出現」,這個算不算違反 INV-1?—— 通常過濾/移除已存在的合法檢索結果應該提前在 recall 層做(例如直接排除掉不該被查到的 source),而不是在 business rule 層事後刪除 ranking 輸出;若必須在後段做(例如法遵/敏感詞即時攔截),要跟使用者明確確認並記錄為「例外情況」,因為這實質上是「刪改」,是 INV-1 明文禁止的操作,需要架構層級的特殊處理(例如獨立於 INV-1 之外的合規攔截層),不要悄悄塞進一般 business rule 策略裡。

## 驗收與測試重點(test-engineer 的紅線測試)

給定一個 sorted BucketList,跑過某個 business rule 策略後:

1. `result.base` 必須與輸入的 sorted BucketList 完全相等(逐 item、逐順序比對)。
2. 把 `result.overlays` 拿掉之後,剩下的東西必須等於 `result.base`,而 `result.base` 又等於原始輸入 —— 這條測試是整個專案的紅線,優先度最高,任何新的 business rule 策略上線前都必須先過這條測試。
