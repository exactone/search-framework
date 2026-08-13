"""Pipeline orchestration —— 把五層介面組裝成一次 search 呼叫。

只做組裝與呼叫順序,不含任何具體檢索/排序/業務演算法。新增一個 RecallStrategy 或
BusinessRule 只需要在建構 Pipeline 時多塞一個物件,run() 本身不需要、也不應該知道
有幾個策略、叫什麼名字 —— 這是 INV-5 在架構層級的具體實現。若這裡出現任何針對特定
策略名稱的 if/else 分支,就是 INV-5 正在被破壞的訊號。

見 docs/design/core-pipeline-design.md §6、§11。

與該文件的一處刻意偏離:文件草案讓 Pipeline 直接持有 MergePlan 並自行遞迴解讀
(execute_merge_plan),但 MergePlan 的樹狀解讀屬於具體演算法,依 CLAUDE.md §7 目錄
慣例應歸 app/recall/(retrieval-engineer 範圍),不屬於 app/core/。這裡改成注入一個
已經包好 MergePlan 的 MergeOperator 實例,Pipeline 只呼叫 `.apply()`,不接觸
MergePlan 本身的解讀邏輯 —— 與其他四層的依賴注入方式一致。

另一處落地:文件草案的 `ranking_groups: Mapping[str, RankingStrategy]` 沒有交代
「這一組要吃哪些 bucket」從何而來(文件 §11 已列為待確認事項)。這裡用 RankingGroup
把 strategy 與它要消費的 bucket_id 參照綁在一起,把這個開放問題落成一個可執行的具體
選擇;之後若要改成由 MCP caller 動態指定分組,只需要調整 Pipeline.run() 的參數,不
影響其他層的介面。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core.interfaces import (
    BusinessRule,
    MergeOperator,
    QueryExpander,
    RankingStrategy,
    RecallStrategy,
)
from app.core.types import Bucket, BucketList, OverlayResult


@dataclass(frozen=True, slots=True)
class RankingGroup:
    """一條 ranking pipeline:哪個策略、吃哪些 bucket(以 bucket_id 參照)。"""

    strategy: RankingStrategy
    bucket_refs: tuple[str, ...]


def select_buckets(pool: Mapping[str, Bucket], bucket_refs: tuple[str, ...]) -> BucketList:
    """依 bucket_id 從候選池挑出一組 bucket,供單一 ranking group 使用。"""
    try:
        return tuple(pool[ref] for ref in bucket_refs)
    except KeyError as exc:
        raise KeyError(f"ranking group references unknown bucket_id {exc.args[0]!r}") from exc


class Pipeline:
    def __init__(
        self,
        expander: QueryExpander,
        recall_strategies: Sequence[RecallStrategy],
        merge_operator: MergeOperator | None,
        ranking_groups: Mapping[str, RankingGroup],
        business_rules: Sequence[BusinessRule],
    ) -> None:
        self._expander = expander
        self._recall_strategies = tuple(recall_strategies)
        self._merge_operator = merge_operator
        self._ranking_groups = dict(ranking_groups)
        self._business_rules = tuple(business_rules)

    def run(self, query: str) -> tuple[OverlayResult, ...]:
        expanded = self._expander.expand(query)

        raw_buckets: BucketList = tuple(
            bucket
            for strategy in self._recall_strategies
            for bucket in strategy.recall(expanded.variants)
        )

        merged: BucketList = (
            self._merge_operator.apply(raw_buckets) if self._merge_operator is not None else ()
        )

        pool: dict[str, Bucket] = {bucket.bucket_id: bucket for bucket in (*raw_buckets, *merged)}

        ranked: BucketList = tuple(
            group.strategy.rank(select_buckets(pool, group.bucket_refs))
            for group in self._ranking_groups.values()
        )

        return tuple(rule.apply(ranked) for rule in self._business_rules)
