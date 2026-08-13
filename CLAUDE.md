# CLAUDE.md — Search Framework (MCP Data Provider)

> 本檔是給 Claude Code 的專案記憶。保持精簡、可執行。規則寫「必須/不可」而非「建議」。
> 領域細節放在 `.claude/skills/`,不要在這裡重複;這裡只放跨所有工作都要遵守的最高層規則。

## 1. 專案目的

建立一個 **search framework**,作為多個異質資料源前面的統一檢索層,並以 **MCP data provider** 的形式對外提供 `search` 能力。上游 caller(其他 MCP client / agent)只看到一個 search 介面,看不到底層資料源差異。

## 2. 資料源(data sources)

| source | 型態 | 檢索特性 |
|---|---|---|
| 全球論文 | 長文本 + metadata | dense + sparse,重 semantic |
| 純數值 table rows | 結構化 | 主要靠條件篩選(filter),非 embedding |
| 投影片 | 圖文混合 | 標題/內文 sparse + 圖說 dense |
| 機台手冊 | 半結構化長文本 | 章節定位 + sparse |
| 各單位先驗知識表 | 結構化知識 | filter + 規則,常作 business rule 來源 |

每個 source 都實作同一個 `DataSource` 介面,回傳統一的 `DataPoint`。新增 source 不得修改各 layer 的程式。

## 3. 核心詞彙(canonical vocabulary)

**這些名詞在整個 codebase 只能有一種定義。** 完整契約見 skill `search-framework-spec`。

- **DataPoint** — 一個單位的資料(一篇論文、一列 row、一張投影片…)。攜帶 `id`、`source`、`payload`、`score`、`provenance`。
- **Bucket** — 一組 DataPoint 的有序或無序集合,帶 `bucket_id` 與 `origin`(哪個 recall 策略產生的)。
- **BucketList** — 多個 Bucket。是 recall / ranking 層之間傳遞的主要單位。

## 4. 管線層(pipeline layers)與不可違反的契約

資料流:`query → Query Expansion → Recall (→ Merge) → Ranking → Business Rule → result`

1. **Query Expansion Layer** — 輸入自然語言或 keyword,輸出「擴增後的查詢集合」(多條 query / 多組 keyword)。純函數,不接觸資料源。
2. **Recall Layer** — 用 sparse / dense / conditional filter 產生**多個 Bucket**,目標是**拉高 recall**,不負責精排。輸出 `BucketList`。
3. **Merge** — Bucket 之間的集合運算(交集 / 聯集 / top-K)。Merge 規則必須是**可組合、可宣告式描述**的(見 skill `recall-and-merge`)。
4. **Ranking Layer** — 對 merged bucket 排序,可有**多條並行的 merge+sort**,輸出**多個 sorted Bucket**(sorted BucketList)。
5. **Business Rule Layer(算法補充層)** — 在**不改動 ranking 輸出**的前提下,將 high-priority 內容(全球熱播、廣告…)**疊加/插入**到結果上。

### 🔒 全域不變式(invariants) — 違反即為 bug

- **INV-1** Business Rule Layer 只能「疊加」不能「重排或刪改」 ranking 的既有輸出;ranking 結果必須可被獨立還原。
- **INV-2** Recall Layer 只負責 recall,**不做最終排序語意**;精排一律在 Ranking Layer。
- **INV-3** 每個 DataPoint 從進入管線到輸出都必須保留 `provenance`(來自哪個 source、哪條 query、哪個 recall 策略)。可觀測性靠這個。
- **INV-4** 各 layer 之間只透過 DataPoint / Bucket / BucketList 傳遞,不得傳 source 專屬結構。
- **INV-5** 新增/替換一個 data source 或一個 recall 策略,**不得修改** ranking / business rule 層程式。

## 5. 技術堆疊(預設值,若不同請在此改)

- 語言:**Python 3.11+**(檢索生態成熟)。若團隊決定改用其他語言,先更新本節再開工。
- 套件/環境:`uv`;測試:`pytest`;型別:`pydantic` v2 定義 DataPoint/Bucket;lint:`ruff`。
- MCP:以官方 MCP server SDK 暴露 `search` tool。

## 6. 常用指令

```bash
uv sync                      # 安裝依賴
uv run pytest                # 全部測試
uv run pytest tests/eval -q  # 只跑檢索評測(recall@k / nDCG)
uv run ruff check . --fix    # lint
uv run python -m app.mcp     # 啟動 MCP data provider(本機)
```
> 若上列指令尚未成立,由 architect 先建立骨架,再回填本節。

## 7. 目錄慣例

```
app/
  core/        # DataPoint / Bucket / BucketList 與介面定義(唯一真相)
  expansion/   # query expansion 策略
  recall/      # recall 策略 + merge
  ranking/     # ranking 策略(可並行)
  business/    # 算法補充層
  sources/     # 各 data source adapter
  mcp/         # MCP data provider 進入點
tests/
  unit/  integration/  eval/
```

## 8. 開發規範

- **契約優先**:動 `app/core/` 的型別前,先確認不破壞第 4/5 節不變式;破壞性變更要在 PR 說明。
- 每個 layer 策略都要能**單獨測試**(給定 input bucket,輸出可預期)。
- 檢索行為的改動必須附**評測數字**(至少 recall@k 前後對比),不接受「感覺變好」。
- 提交訊息用祈使句、聚焦單一改動。不要一次 PR 動多層。

## 9. 這個專案的 sub-agent(何時交給誰)

- `spec-writer` — 把口語需求改寫成結構化 spec / 驗收標準。
- `architect` — 設計層間介面、資料模型、MCP 介面。動 `app/core/` 前先找它。
- `retrieval-engineer` — 實作各層策略與 source adapter。
- `test-engineer` — 寫測試與檢索評測。
- `code-reviewer` — 唯讀審查,合併前跑一次。

領域知識都在 `.claude/skills/`,各 agent 已於 frontmatter 預載相關 skill。
