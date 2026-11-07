
from pydantic import BaseModel


class AppointmentCreate(BaseModel):
    patient_id: str
    doctor_id: str
    slot_id: str


class AppointmentReschedule(BaseModel):
    new_slot_id: str
