from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TransactionWebhook(BaseModel):
    transaction_id: str = Field(min_length=1)
    source_account: str = Field(min_length=1)
    destination_account: str = Field(min_length=1)
    amount: float
    currency: str = Field(min_length=1)


class HealthResponse(BaseModel):
    status: str
    current_time: datetime


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: str
    source_account: str
    destination_account: str
    amount: float
    currency: str
    status: str
    created_at: datetime
    processed_at: datetime | None
