from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class SubscriptionBase(BaseModel):
    provider: str = Field(default="wayforpay", max_length=50)
    status: str = Field(default="pending", max_length=32)
    expires_at: Optional[datetime] = None


class SubscriptionCreate(SubscriptionBase):
    user_id: int
    payload: Optional[dict[str, Any]] = None


class SubscriptionRead(SubscriptionBase):
    id: int
    user_id: int
    payload: Optional[dict[str, Any]] = None
    created_at: datetime

    model_config = {
        "from_attributes": True,
    }
