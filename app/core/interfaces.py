"""五層 pipeline 的介面契約(Protocol)。

只定義「形狀」,不含任何具體演算法。實作交給 retrieval-engineer(app/expansion/,
app/recall/, app/ranking/, app/business/),介面本身不得變動以配合單一實作 —— 若某個
實作發現介面不夠用,回頭找 architect 調整介面,不要繞過去。

見 docs/design/core-pipeline-design.md §5。
"""

from typing import Protocol, runtime_checkable

from app.core.types import (
    Bucket,
    BucketList,
    ExpandedQuery,
    OverlayResult,
    QueryVariant,
)


@runtime_checkable
class QueryExpander(Protocol):
    def expand(self, query: str) -> ExpandedQuery:
        """純函數。不得存取任何 data source、不得有副作用。"""
        ...


@runtime_checkable
class RecallStrategy(Protocol):
    name: str  # 寫入 Bucket.origin,例如 "dense_pgvector_papers"

    def recall(self, variants: tuple[QueryVariant, ...]) -> BucketList:
        """回傳的每個 Bucket.sorted 必須是 False。

        介面刻意不提供任何排序/精排相關參數 —— 這是 INV-2 在介面層級的強制:
        呼叫端沒有管道要求這個策略「順便排序」。
        """
        ...


@runtime_checkable
class MergeOperator(Protocol):
    def apply(self, buckets: BucketList) -> BucketList:
        """對輸入 bucket 執行宣告式的集合運算(見 MergePlan)。

        輸出的每個 Bucket.sorted 必須維持 False(INV-2)。具體的 intersect/union/
        top_k 實作(含 MergePlan 樹的遞迴解讀)屬於 retrieval-engineer 範圍,不在
        app/core/ 內。
        """
        ...


@runtime_checkable
class RankingStrategy(Protocol):
    def rank(self, grouped_buckets: BucketList) -> Bucket:
        """把呼叫端指定的一組 bucket 融合成單一個 sorted Bucket(sorted=True)。

        一次 pipeline 執行可以並行呼叫多個 RankingStrategy 實例、餵不同的分組,
        產生多個互相獨立的 sorted Bucket —— 分組本身由呼叫端(Pipeline)決定,見
        pipeline.py 的 RankingGroup。
        """
        ...


@runtime_checkable
class BusinessRule(Protocol):
    def apply(self, ranked: BucketList) -> OverlayResult:
        """`ranked` 視為唯讀輸入,不得排序/刪除/修改既有項目 —— 只能疊加(INV-1)。

        因為 Bucket/DataPoint 皆為 frozen model、BucketList 是 tuple,嘗試在實作內
        部「原地修改」在型別系統層級就會失敗,而不是留到測試才發現。
        """
        ...
