"""Application-level configuration."""

from pathlib import Path

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Configuration needed before external clients are initialized."""

    title: str = Field(default="CRM API")
    description: str = Field(
        default="CRM and appointment scheduling for service businesses"
    )
    version: str = Field(default="0.1.0")
    static_dir: Path = Field(default=Path("static"))
