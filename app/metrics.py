import threading
import time
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Iterator

from app.config import INPUT_PRICE_PER_MTOK, OUTPUT_PRICE_PER_MTOK
from app.cache import is_enabled


@dataclass
class StageMetrics:
    llm_real_calls: int = 0
    llm_cache_hits: int = 0
    searches_real: int = 0
    searches_cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0


class Metrics:
    """Collect process-local LLM, search, token, and stage timing metrics."""

    def __init__(self) -> None:
        self._current_stage: ContextVar[str] = ContextVar(
            "metrics_current_stage", default="other"
        )
        self._lock = threading.Lock()
        self._stages: dict[str, StageMetrics] = {}

    def _stage_metrics(self, name: str | None = None) -> StageMetrics:
        stage_name = name or self._current_stage.get()
        return self._stages.setdefault(stage_name, StageMetrics())

    def reset(self) -> None:
        with self._lock:
            self._stages.clear()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        token = self._current_stage.set(name)
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            with self._lock:
                self._stage_metrics(name).seconds += elapsed
                self._current_stage.reset(token)

    def record_llm_call(self, *, cache_hit: bool = False) -> None:
        with self._lock:
            metrics = self._stage_metrics()
            if cache_hit:
                metrics.llm_cache_hits += 1
            else:
                metrics.llm_real_calls += 1

    def record_search(self, *, cache_hit: bool = False) -> None:
        with self._lock:
            metrics = self._stage_metrics()
            if cache_hit:
                metrics.searches_cache_hits += 1
            else:
                metrics.searches_real += 1

    def record_tokens(self, input_tokens: int | None, output_tokens: int | None) -> None:
        with self._lock:
            metrics = self._stage_metrics()
            metrics.input_tokens += input_tokens or 0
            metrics.output_tokens += output_tokens or 0

    def snapshot(self) -> dict:
        with self._lock:
            stages = {
                name: asdict(values)
                for name, values in sorted(self._stages.items())
            }
        input_tokens = sum(item["input_tokens"] for item in stages.values())
        output_tokens = sum(item["output_tokens"] for item in stages.values())
        estimated_cost = (
            input_tokens * INPUT_PRICE_PER_MTOK
            + output_tokens * OUTPUT_PRICE_PER_MTOK
        ) / 1_000_000
        return {
            "uncached": not is_enabled(),
            "stages": stages,
            "input_price_per_mtok": INPUT_PRICE_PER_MTOK,
            "output_price_per_mtok": OUTPUT_PRICE_PER_MTOK,
            "estimated_cost": estimated_cost,
        }

    def summary(self) -> str:
        data = self.snapshot()
        label = (
            "CACHED RUN (some calls may be cache hits)"
            if is_enabled()
            else "UNCACHED RUN"
        )
        headings = (
            f"{label}\n"
            "Stage      LLM real/cache  Search real/cache  Input/output tokens  Seconds"
        )
        rows = []
        for name, values in data["stages"].items():
            rows.append(
                f"{name:<10} "
                f"{values['llm_real_calls']:>4}/{values['llm_cache_hits']:<4} "
                f"{values['searches_real']:>6}/{values['searches_cache_hits']:<5} "
                f"{values['input_tokens']:>8}/{values['output_tokens']:<8} "
                f"{values['seconds']:>7.2f}"
            )
        if not rows:
            rows.append("(no stages recorded)")
        return (
            f"{headings}\n" + "\n".join(rows)
            + f"\nEstimated cost: ${data['estimated_cost']:.6f}"
        )


metrics = Metrics()
