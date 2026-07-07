from collections.abc import AsyncIterator
from typing import TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel

from api.core.config import settings
from api.llm.client import LLMClient, LLMClientError

T = TypeVar("T", bound=BaseModel)


class GeminiLLMClient(LLMClient):
    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        self._client = genai.Client(api_key=api_key if api_key is not None else settings.gemini_api_key)
        self._model_name = model_name if model_name is not None else settings.gemini_model_name

    async def generate(self, prompt: str) -> AsyncIterator[str]:
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model_name,
                contents=prompt,
            )
            async for chunk in stream:
                if chunk.text:
                    yield chunk.text
        except genai_errors.APIError as exc:
            raise LLMClientError(f"Gemini generate() call failed: {exc}") from exc

    async def generate_structured(self, prompt: str, response_schema: type[T]) -> T:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                ),
            )
        except genai_errors.APIError as exc:
            raise LLMClientError(f"Gemini generate_structured() call failed: {exc}") from exc

        if not isinstance(response.parsed, response_schema):
            raise LLMClientError(
                f"Gemini structured response could not be parsed into {response_schema.__name__}"
            )
        return response.parsed
