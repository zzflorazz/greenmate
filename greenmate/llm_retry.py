"""Bounded retries of one LLM HTTP request, never of the surrounding workflow."""
import asyncio
from openai import APIConnectionError, OpenAIError

RETRY_STATUS_CODES = {502, 503, 504}
MAX_ATTEMPTS = 3


def error_details(error: Exception | None, message: str) -> dict:
    # Do not expose provider response bodies, URLs, headers or credentials.
    # null means that no upstream HTTP response was received (e.g. timeout).
    return {'status_code': getattr(error, 'status_code', None), 'message': message}


async def create_completion_with_retry(client, **kwargs):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = await client.chat.completions.create(**kwargs)
        except OpenAIError as error:
            code = getattr(error, 'status_code', None)
            retryable = isinstance(error, APIConnectionError) or code in RETRY_STATUS_CODES
            print(f'[llm.attempt] attempt={attempt} error_type={type(error).__name__} status_code={code}', flush=True)
            if not retryable or attempt == MAX_ATTEMPTS:
                raise
            await asyncio.sleep(attempt)  # First retry after 1s, second after 2s.
        else:
            print(f'[llm.attempt] attempt={attempt} error_type=None status_code=200', flush=True)
            return result
