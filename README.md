# Search Framework — Claude Code 開發骨架

這是一套 **開發期(build-time)** 的 Claude Code 設定,把「多資料源前的統一 search 層 + MCP data provider」這個 backend framework 定義出來。它本身不含實作程式碼,而是提供 search 框架讓不同源的 search 可以 fit-in。

## 檔案結構
```
search-framework/
├── CLAUDE.md                     # 專案記憶:目的/層契約/不變式/規範(每個 agent 都會載入)
├── .claude/
│   ├── agents/                   # 4 個開發角色(sub-agents)
│   │   ├── spec-writer.md        #   自然語言需求 → 結構化 spec
│   │   ├── architect.md          #   介面契約框架 / 資料模型框架 / 各層 (query expansion, recall, ranking, business rule) & datapoint, bucket, bucket list 軟體工程框架 /MCP 介面框架
|   |   ├── retrieval-engineer.md #   實作 recall 策略 + ranking 策略 + business rule 策略
│   │   └── test-engineer.md      #   撰寫 demo use case + 測試 + 檢索評測 (recall@k, precision@k, NDCG@k)
│   └── skills/                   # 領域知識(agent 透過 frontmatter `skills:` 預載共用)
│       ├── search-framework-spec/  # 核心契約(所有 agent 共用)
│       ├── query-expansion/
│       ├── recall-and-merge/
│       ├── ranking-layer/
│       ├── business-rule-layer/
│       ├── mcp-data-provider/
│       └── retrieval-eval/
```

## 怎麼開始
1. 把整個 `search-framework/` 當作專案根目錄,`cd` 進去後啟動 `claude`。
2. 先確認技術堆疊:打開 `CLAUDE.md` 第 5 節,若不是 Python 就改掉。
3. 用角色驅動開發,例如:
   - `用 spec-writer 把「我想讓數值表也能被語意查詢」寫成 spec`
   - `用 architect 依這份 spec 設計 DataPoint 與 recall 介面,寫 ADR`
   - `用 retrieval-engineer 實作 dense recall 策略`
   - `用 test-engineer 補單元測試與 recall@k 評測`
   - `合併前用 code-reviewer 審一次`

> 首次新增 agent/skill 檔後,若 Claude Code 已在執行,重啟一次讓它載入。

## 設計理念(兩個重點)
- **角色歸 agent,知識歸 skill**:領域規則寫一次放在 skill,多個 agent 共用,不重複、不漂移。改契約只改 `search-framework-spec` 這個 skill。
- **不變式是第一公民**:`CLAUDE.md` 的 INV-1..INV-5 是所有角色的紅線,尤其算法補充層「只疊加不重排」(INV-1)。code-reviewer 與 test-engineer 都以此為回歸檢查。

## 關於「最好的 CLAUDE.md 範本」
沒有單一權威範本;本專案的 `CLAUDE.md` 已依 Anthropic 對 Claude Code memory 的建議寫成(精簡、可執行、規則化)。若要找更多範例,參考:
- 官方文件:Claude Code「Memory / CLAUDE.md」與「Subagents」頁(code.claude.com/docs)。
- 社群整理:`awesome-claude-code` 類 repo 有大量 CLAUDE.md 與 subagent 範例。
判準是:**短、命令式、把慣例與紅線寫死、把領域細節外移到 skill**——避免變成沒人維護的長文件。
