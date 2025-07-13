from typing import Dict, Optional
from pydantic import BaseModel

class RoutineBase(BaseModel):
    name: str
    description: Optional[str] = None
    schedule: Dict[str, str]  # contoh: {"day_1": "push", "day_2": "pull"}

class RoutineCreate(RoutineBase):
    pass

class RoutineOut(RoutineBase):
    id: int
    user_id: int

    class Config:
        orm_mode = True