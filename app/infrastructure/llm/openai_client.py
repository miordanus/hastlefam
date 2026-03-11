from openai import AsyncOpenAI
from app.infrastructure.config.settings import get_settings


class OpenAIProvider:
    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model

    async def generate_json(self, *, system_prompt: str, user_prompt: str, schema: dict) -> dict:
        response = await self.client.responses.create(
            model=self.model,
            input=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            response_format={'type': 'json_schema', 'json_schema': {'name': 'contract', 'schema': schema}},
        )
        text = response.output_text
        import json
        return json.loads(text)
