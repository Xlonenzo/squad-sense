from pydantic import BaseModel, Field


class BootstrapProjectResponse(BaseModel):
    project_key: str
    project_id: str
    project_name: str
    created: bool = Field(
        description="True se o projeto foi criado nesta chamada; False se já existia."
    )
    mode: str = Field(description="'mock' ou 'rest' — qual cliente foi usado")


class BootstrapSeedResponse(BaseModel):
    project_key: str
    sprints_created: int
    issues_created: int
    epics_created: int
    mode: str
    planted_patterns: list[str] = Field(
        default_factory=list,
        description="Sumário dos sinais plantados — para conferência manual.",
    )
