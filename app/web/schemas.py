from pydantic import BaseModel


class HelloResponse(BaseModel):
    greeting: str
    is_registered: bool
    readiness: str | None
