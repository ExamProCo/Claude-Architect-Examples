import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")

_logger = logging.getLogger("coordinator")
_logger.setLevel(logging.INFO)
_logger.propagate = False

_ch = logging.StreamHandler(sys.stdout)
_ch.setFormatter(_fmt)
_logger.addHandler(_ch)

_fh = logging.FileHandler(_LOG_DIR / "coordinator.log")
_fh.setFormatter(_fmt)
_logger.addHandler(_fh)


class _TaggedLogger:
    def partition(self, msg: str, *args) -> None:
        _logger.info("[PARTITION] " + msg, *args)

    def delegate(self, step: int, partition: str, question: str) -> None:
        _logger.info("[DELEGATE] step=%d partition=%s question=%s", step, partition, question)

    def spoke_result(self, partition: str, response: str) -> None:
        _logger.info("[SPOKE_RESULT] partition=%s response=%s", partition, response[:200])

    def coordinator(self, step: int, text: str) -> None:
        _logger.info("[COORDINATOR] step=%d text=%s", step, text[:300])

    def coverage(self, step: int, score, sufficient: bool, gaps: list) -> None:
        _logger.info("[COVERAGE] step=%d score=%s/10 sufficient=%s gaps=%s", step, score, sufficient, gaps)

    def final(self, verdict: dict) -> None:
        _logger.info(
            "[FINAL] verdict=%s strengths=%s concerns=%s rationale=%s",
            verdict["verdict"],
            verdict["key_strengths"],
            verdict["key_concerns"],
            verdict["rationale"],
        )

    def trace(self, i: int, entry: dict) -> None:
        _logger.info(
            "[TRACE] i=%d ts=%s partition=%s question=%s response=%s",
            i, entry["timestamp"], entry["partition_agent"],
            entry["question"], entry["response"][:200],
        )

    def coverage_dimension(self, dimension: str, covered: bool) -> None:
        _logger.info("[COVERAGE_REPORT] dimension=%s covered=%s", dimension, covered)

    def warn(self, msg: str, *args) -> None:
        _logger.warning("[WARN] " + msg, *args)

    def error(self, msg: str, *args) -> None:
        _logger.error("[ERROR] " + msg, *args)


log = _TaggedLogger()


def ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
