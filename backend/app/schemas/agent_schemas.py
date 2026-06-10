from pydantic import BaseModel

class ReviewRequest(BaseModel):
    code: str
    project_name: str | None = None
