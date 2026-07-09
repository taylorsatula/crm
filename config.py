"""Application-level configuration."""

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Configuration needed before external clients are initialized."""

    title: str = Field(default="CRM Internal Service")
    description: str = Field(
        default="Private, workspace-scoped CRM business-data service"
    )
    version: str = Field(default="0.1.0")
    expose_docs: bool = Field(default=False)
