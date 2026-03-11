from dataclasses import dataclass
from app.infrastructure.llm.validators import validate_contract_output
from app.infrastructure.logging.logger import get_logger

logger = get_logger('llm')


@dataclass
class LLMContractFailure:
    contract: str
    error: str


class LLMService:
    def __init__(self, provider):
        self.provider = provider

    async def run_contract(self, contract_name: str, system_prompt: str, user_prompt: str, schema: dict):
        raw = await self.provider.generate_json(system_prompt=system_prompt, user_prompt=user_prompt, schema=schema)
        validated, err = validate_contract_output(contract_name, raw)
        if err:
            logger.error('llm.validation_failed', contract=contract_name, error=err)
            return LLMContractFailure(contract=contract_name, error=err)
        logger.info('llm.validation_ok', contract=contract_name)
        return validated
