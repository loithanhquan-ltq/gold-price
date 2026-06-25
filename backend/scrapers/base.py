from dataclasses import dataclass, asdict
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception


def _is_retryable(exc: BaseException) -> bool:
    """Don't retry on rate-limit or auth errors — they won't resolve with more requests."""
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return exc.response.status_code not in (429, 401, 403, 404)
    return True


network_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=15),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)


@dataclass
class PriceResult:
    source: str
    currency: str
    unit: str
    buy_price: float | None = None
    sell_price: float | None = None
    high: float | None = None
    low: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)
