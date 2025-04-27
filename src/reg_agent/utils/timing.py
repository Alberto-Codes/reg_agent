import time
import asyncio
import functools
from typing import Callable, Any, Optional
import structlog

log = structlog.get_logger()

def log_task_duration(task_name_override: Optional[str] = None) -> Callable:
    """
    Decorator to log the start, end, and duration of a function or coroutine.

    Uses time.monotonic() for reliable duration measurement.
    Logs output using structlog.

    Args:
        task_name_override: Optional name to use for the task in logs.
                            Defaults to the function's __name__.

    Returns:
        The decorator function.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        task_name = task_name_override or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            log.info(f"Starting task: {task_name}", task=task_name)
            start_time = time.monotonic()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                end_time = time.monotonic()
                duration = end_time - start_time
                log.info(
                    f"Finished task: {task_name}",
                    task=task_name,
                    duration_seconds=f"{duration:.2f}",
                )

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            log.info(f"Starting task: {task_name}", task=task_name)
            start_time = time.monotonic()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                end_time = time.monotonic()
                duration = end_time - start_time
                log.info(
                    f"Finished task: {task_name}",
                    task=task_name,
                    duration_seconds=f"{duration:.2f}",
                )

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            # Although ingest_files is async, parts might call sync functions
            # This ensures the decorator *could* be used for sync functions too.
            return sync_wrapper

    return decorator 