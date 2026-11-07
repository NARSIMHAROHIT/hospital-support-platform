
from typing import Literal
from pydantic import BaseModel, Field


Category = Literal[
    "appointment", "billing", "portal_access", "general"
]

Status = Literal["open", "in_progress", "resolved"]


class PatientQuery(BaseModel):
    patient_id: str = Field(min_length=1, max_length=50)
    category: Category
    question: str = Field(min_length=5, max_length=1000)


class StatusUpdate(BaseModel):
    status: Status


class PriorityUpdate(BaseModel):
    priority: Literal["low", "medium", "high"]


class AssignmentUpdate(BaseModel):
    department: Literal[
        "general", "billing", "appointments", "it_support"
    ]
    assigned_to: str | None = Field(
        default=None,
        max_length=50
    )
