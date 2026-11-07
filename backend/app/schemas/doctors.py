
from datetime import datetime
from pydantic import BaseModel, Field


class DoctorCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    specialization: str = Field(min_length=2, max_length=100)
    department: str = Field(min_length=2, max_length=100)


class AvailabilityCreate(BaseModel):
    starts_at: datetime
    ends_at: datetime
