"""核心資料模型 —— DataPoint / Bucket / BucketList 與相關型別。

見 docs/design/core-pipeline-design.md §4 與 docs/specs/search-framework-core-pipeline.md。
所有型別採 pydantic v2 + frozen=True + tuple(而非 list),讓「業務規則層不可原地修改
既有輸出」(INV-1)在型別系統層級就不可能發生,而不是只能靠 code review 抓。

注意:frozen 只保護 model 本身的欄位不被重新賦值,不會深度凍結 payload 這種原生
dict —— 呼叫端仍應把 DataPoint.payload 當唯讀使用,但型別系統無法強制這件事。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    """INV-3:每個 DataPoint 的可追溯資訊。stage_trace 只能透過 with_stage() 累加。"""

    model_config = ConfigDict(frozen=True)

    source: str
    query_id: str
    recall_strategy: str
    stage_trace: tuple[str, ...] = Field(default_factory=tuple)

    def with_stage(self, stage: str) -> "Provenance":
        return self.model_copy(update={"stage_trace": (*self.stage_trace, stage)})


class DataPoint(BaseModel):
    """跨層傳遞的最小單位。source 專屬內容一律收斂在 payload(INV-4)。"""

    model_config = ConfigDict(frozen=True)

    id: str
    source: str
    payload: dict[str, object]
    score: float | None = None
    provenance: Provenance


class Bucket(BaseModel):
    """一組 DataPoint。sorted=False 是預設值,只有 Ranking Layer 能把它變 True(INV-2)。"""

    model_config = ConfigDict(frozen=True)

    bucket_id: str
    origin: str
    items: tuple[DataPoint, ...]
    sorted: bool = False


BucketList = tuple[Bucket, ...]


class QueryVariant(BaseModel):
    """Query Expansion 產生的其中一條擴增查詢。"""

    model_config = ConfigDict(frozen=True)

    query_id: str
    text: str
    intent: Literal["dense", "sparse", "filter", "generic"]
    weight: float = 1.0


class ExpandedQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    original_query: str
    variants: tuple[QueryVariant, ...]


class MergePlan(BaseModel):
    """Bucket List Operation 的宣告式描述(交集/聯集/top-K),可組合、可序列化。

    inputs 裡的 str 是 bucket_id 參照,指向 recall 階段或另一個 MergePlan 節點產出的
    bucket。具體的樹狀解讀邏輯屬於 retrieval-engineer 在 app/recall/ 下的實作範圍,
    這裡只定義結構本身。
    """

    model_config = ConfigDict(frozen=True)

    op: Literal["intersect", "union", "top_k"]
    inputs: tuple["MergePlan | str", ...]
    top_k: int | None = None
    by: str = "score"


MergePlan.model_rebuild()


class OverlayItem(BaseModel):
    """Business Rule Layer 疊加的單一項目。"""

    model_config = ConfigDict(frozen=True)

    content: "Bucket | DataPoint"
    placement: Literal["pin_top", "append_bucket", "inline_at"]
    reason: str


class OverlayResult(BaseModel):
    """INV-1 的型別化保證:base 與 overlays 分離,base 必須等於 ranking 的原始輸出。"""

    model_config = ConfigDict(frozen=True)

    base: BucketList
    overlays: tuple[OverlayItem, ...]

    def restore_base(self) -> BucketList:
        return self.base
