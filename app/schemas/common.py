# app/schemas/common.py
from pydantic import BaseModel
from typing import List

class UserIdsRequest(BaseModel):
    user_ids: List[str]