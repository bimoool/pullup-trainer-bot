from pydantic import BaseModel


class HelloResponse(BaseModel):
    name: str
    is_onboarded: bool
    readiness_status: str | None
    days_since_last_workout: int | None
