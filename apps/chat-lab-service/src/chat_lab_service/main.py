"""uvicorn `--factory` 진입점 — 환경 변수에서 설정을 읽어 앱을 만든다."""

from fastapi import FastAPI

from chat_lab_service.app import create_app
from chat_lab_service.settings import Settings


def create_app_from_env() -> FastAPI:
    return create_app(Settings())
