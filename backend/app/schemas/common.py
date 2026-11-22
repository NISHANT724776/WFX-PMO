from datetime import datetime
from typing import Generic, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, create_model

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


def make_update_schema(create_schema: type[BaseModel]) -> type[BaseModel]:
    fields = {n: (Optional[f.annotation], None) for n, f in create_schema.model_fields.items()}
    return create_model("Update" + create_schema.__name__, __base__=ORMModel, **fields)


def make_read_schema(create_schema: type[BaseModel]) -> type[BaseModel]:
    return create_model(
        create_schema.__name__.replace("Create", "") + "Read",
        __base__=create_schema,
        id=(UUID, ...),
        created_at=(Optional[datetime], None),
    )
