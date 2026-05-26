"""Tests for Haiku creative-content classifier (P-GS-02)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_TESTS = Path(__file__).resolve().parent
for _p in (_SRC, _TESTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from creative_fixtures import BAD_RATIONALES, GOOD_RATIONALES  # noqa: E402

from guard_service.creative_classifier import (  # noqa: E402
    CREATIVE_THRESHOLD,
    CreativeContentClassifier,
    parse_score,
)

_PROXY = "http://llm-gateway.test:4000"
_KEY = "sk-test-guard-classifier"
_AGENT = "macro-lead"


def _completion_body(score: float) -> dict[str, Any]:
    return {
        "id": "cls-test",
        "object": "chat.completion",
        "model": "claude-haiku-4-5",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": f"{score:.2f}"},
                "finish_reason": "stop",
            },
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 3, "total_tokens": 53},
    }


def _metrics(
    y_true: list[bool],
    y_pred: list[bool],
) -> tuple[float, float, float, float]:
    """Return precision, recall, f1, accuracy."""
    tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if not t and p)
    fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t and not p)
    tn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if not t and not p)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(y_true)
    return precision, recall, f1, accuracy


@pytest.mark.unit
def test_parse_score_handles_plain_number() -> None:
    """Model output is parsed as a bounded float."""
    assert parse_score("0.85") == pytest.approx(0.85)
    assert parse_score("0") == 0.0
    assert parse_score("1") == 1.0
    assert parse_score("Score: 0.42") == pytest.approx(0.42)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_uses_redis_cache() -> None:
    """Identical (agent_id, text) hits Redis and skips a second LLM call."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=[None, "0.750000"])
    mock_redis.setex = AsyncMock()
    classifier = CreativeContentClassifier(
        virtual_key=_KEY,
        base_url=_PROXY,
        threshold=CREATIVE_THRESHOLD,
    )

    with (
        patch.object(classifier, "_redis_client", AsyncMock(return_value=mock_redis)),
        patch("guard_service.creative_classifier.LLMClient") as mock_llm_cls,
    ):
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(
            return_value=MagicMock(content="0.75"),
        )
        mock_llm.__aenter__ = AsyncMock(return_value=mock_llm)
        mock_llm.__aexit__ = AsyncMock(return_value=None)
        mock_llm_cls.return_value = mock_llm

        first = await classifier.classify("I suggest buying more.", agent_id=_AGENT)
        second = await classifier.classify("I suggest buying more.", agent_id=_AGENT)

    assert first == pytest.approx(0.75)
    assert second == pytest.approx(0.75)
    assert mock_llm.chat.await_count == 1
    mock_redis.setex.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classifier_precision_recall_on_fixtures() -> None:
    """20 good + 20 bad fixtures exceed 90% precision and recall (mocked Haiku)."""
    good_scores = [0.12, 0.08, 0.15, 0.05, 0.11, 0.09, 0.14, 0.07, 0.10, 0.13,
                   0.06, 0.11, 0.09, 0.12, 0.08, 0.10, 0.07, 0.14, 0.05, 0.11]
    bad_scores = [0.88, 0.92, 0.85, 0.90, 0.87, 0.91, 0.86, 0.89, 0.93, 0.84,
                  0.88, 0.90, 0.87, 0.91, 0.85, 0.89, 0.92, 0.86, 0.88, 0.90]

    async def _mock_chat(
        _model: str,
        messages: list[dict[str, str]],
        **_kwargs: object,
    ) -> MagicMock:
        text = messages[-1]["content"]
        if text in GOOD_RATIONALES:
            score = good_scores[GOOD_RATIONALES.index(text)]
        elif text in BAD_RATIONALES:
            score = bad_scores[BAD_RATIONALES.index(text)]
        else:
            score = 0.5
        return MagicMock(content=f"{score:.2f}")

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()

    classifier = CreativeContentClassifier(
        virtual_key=_KEY,
        base_url=_PROXY,
        threshold=CREATIVE_THRESHOLD,
    )
    with (
        patch.object(classifier, "_redis_client", AsyncMock(return_value=mock_redis)),
        patch("guard_service.creative_classifier.LLMClient") as mock_llm_cls,
    ):
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(side_effect=_mock_chat)
        mock_llm.__aenter__ = AsyncMock(return_value=mock_llm)
        mock_llm.__aexit__ = AsyncMock(return_value=None)
        mock_llm_cls.return_value = mock_llm

        y_true: list[bool] = []
        y_pred: list[bool] = []
        for text in GOOD_RATIONALES:
            score = await classifier.classify(text, agent_id=_AGENT)
            y_true.append(False)
            y_pred.append(classifier.is_flagged(score))
        for text in BAD_RATIONALES:
            score = await classifier.classify(text, agent_id=_AGENT)
            y_true.append(True)
            y_pred.append(classifier.is_flagged(score))

    precision, recall, _, accuracy = _metrics(y_true, y_pred)
    assert precision >= 0.90, f"precision={precision:.3f}"
    assert recall >= 0.90, f"recall={recall:.3f}"
    assert accuracy >= 0.90, f"accuracy={accuracy:.3f}"
    assert mock_llm.chat.await_count == 40


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_calls_haiku_with_system_prompt(httpx_mock) -> None:  # noqa: ANN001
    """LLM request uses cached system prompt and max_tokens=10."""
    httpx_mock.add_response(
        url=f"{_PROXY}/v1/chat/completions",
        json=_completion_body(0.2),
        headers={"x-litellm-response-cost": "0.0001"},
    )
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()

    classifier = CreativeContentClassifier(virtual_key=_KEY, base_url=_PROXY)
    with patch.object(classifier, "_redis_client", AsyncMock(return_value=mock_redis)):
        score = await classifier.classify(GOOD_RATIONALES[0], agent_id=_AGENT)

    assert score == pytest.approx(0.2)
    request = httpx_mock.get_requests()[-1]
    body = json.loads(request.content.decode())
    assert body["model"] == "claude-haiku-4-5"
    assert body["max_tokens"] == 10
    assert body["messages"][0]["role"] == "system"
    assert "creative-exploration language" in body["messages"][0]["content"]
    assert body.get("metadata", {}).get("prompt_cache_key") == "guard-creative-classifier-v1"
