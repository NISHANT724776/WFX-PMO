from datetime import date
from typing import Literal, Optional
from uuid import UUID

from pydantic import EmailStr, Field

from app.schemas.common import ORMModel

Code = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_.\-]+$")


class CustomerCreate(ORMModel):
    code: str = Code
    name: str = Field(min_length=1, max_length=200)
    country: Optional[str] = Field(None, max_length=100)
    is_active: bool = True


class ProductCreate(ORMModel):
    code: str = Code
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    is_active: bool = True


class DepartmentCreate(ORMModel):
    code: str = Code
    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True


class LocationCreate(ORMModel):
    code: str = Code
    name: str = Field(min_length=1, max_length=200)
    country: Optional[str] = Field(None, max_length=100)
    timezone: Optional[str] = Field(None, max_length=64)
    is_active: bool = True


class ResourceCreate(ORMModel):
    full_name: str = Field(min_length=1, max_length=150)
    email: Optional[EmailStr] = None
    department_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    is_active: bool = True


class StatusConfigCreate(ORMModel):
    entity_type: str = Field(min_length=1, max_length=50)
    code: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=100)
    category: Literal["not_started", "in_progress", "done", "cancelled", "blocked"]
    color: Optional[str] = Field(None, max_length=20)
    sort_order: int = 0


# ---- projects ----
class ProductOut(ORMModel):
    id: UUID
    code: str
    name: str


class LocationOut(ORMModel):
    id: UUID
    code: str
    name: str
    country: Optional[str] = None


class ProjectProductOut(ORMModel):
    id: UUID
    product_id: UUID
    go_live_date: Optional[date] = None
    product: ProductOut


class ProjectSiteOut(ORMModel):
    id: UUID
    location_id: UUID
    entity_name: Optional[str] = None
    location: LocationOut


class ProjectCreate(ORMModel):
    customer_id: UUID
    code: str = Code
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    status: str = Field("Planned", max_length=30)
    start_date: Optional[date] = None
    target_go_live: Optional[date] = None
    manager_id: Optional[UUID] = None
    delay_grace_days: int = Field(0, ge=0, le=60)


class ProjectUpdate(ORMModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    status: Optional[str] = Field(None, max_length=30)
    start_date: Optional[date] = None
    target_go_live: Optional[date] = None
    manager_id: Optional[UUID] = None
    delay_grace_days: Optional[int] = Field(None, ge=0, le=60)


class ProjectRead(ProjectCreate):
    id: UUID
    products: list[ProjectProductOut] = []
    sites: list[ProjectSiteOut] = []


class AddProduct(ORMModel):
    product_id: UUID
    go_live_date: Optional[date] = None


class AddSite(ORMModel):
    location_id: UUID
    entity_name: Optional[str] = Field(None, max_length=200)
