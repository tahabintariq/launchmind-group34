from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable, TypeVar


F = TypeVar("F", bound=Callable[..., Any])


def retry(tries: int = 3, delays: tuple[int, ...] = (1, 2, 4)) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Exception | None = None
            for attempt in range(tries):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_error = exc
                    if attempt >= tries - 1:
                        break
                    time.sleep(delays[min(attempt, len(delays) - 1)])
            raise last_error or RuntimeError("Unknown retry failure")

        return wrapper  # type: ignore[return-value]

    return decorator
