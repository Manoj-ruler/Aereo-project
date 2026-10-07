"""FastAPI dependencies wiring settings, sessions and services together."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.repositories import FileRepository
from app.services.file_service import FileService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_file_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> FileService:
    return FileService(FileRepository(session), settings)


FileServiceDep = Annotated[FileService, Depends(get_file_service)]
