from app.infrastructure.logging.logger import get_logger

logger = get_logger('prompt')


def log_prompt(contract: str, input_payload: dict):
    logger.info('llm.prompt', contract=contract, input=input_payload)
