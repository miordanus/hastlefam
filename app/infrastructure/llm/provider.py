from typing import Protocol


class LLMProvider(Protocol):
    async def generate_json(self, *, system_prompt: str, user_prompt: str, schema: dict) -> dict:
        ...
