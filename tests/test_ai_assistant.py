"""Offline tests for the AI concierge (src/core/ai_assistant.py).

No network, no API key: the DeepSeek client is monkeypatched. Verifies:
  * graceful degradation when the LLM is unavailable (returns None),
  * the recommender's prompt is built from ONLY the real deal numbers,
  * responses are cached (no duplicate billing on repeat taps).

Run:  python -m pytest tests/test_ai_assistant.py -q
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.utils.compat  # noqa

from src.core import ai_assistant as ai


DEALS = [
    {"destination": "VIE", "dest_city": "Vienna", "grand_total": 142,
     "total_price": 100, "outbound_date": "2026-08-03",
     "return_date": "2026-08-06", "confidence_label": "HIGH",
     "participants": [{"label": "You", "price": 60},
                      {"label": "Sara", "price": 40}]},
    {"destination": "BUD", "dest_city": "Budapest", "grand_total": 158,
     "total_price": 120, "outbound_date": "2026-08-03",
     "return_date": "2026-08-06", "confidence_label": "MEDIUM",
     "participants": [{"label": "You", "price": 70},
                      {"label": "Sara", "price": 50}]},
]


class _FakeClient:
    """Stand-in DeepSeekClient that records prompts and returns canned text."""
    def __init__(self, key="x"):
        self.key = key
        self.calls = []

    def available(self):
        return bool(self.key)

    def chat(self, system, user, **kw):
        self.calls.append({"system": system, "user": user, **kw})
        return "Go with Vienna - cheapest and fairest."


def _patch(monkeypatch, client):
    monkeypatch.setattr(ai, "_client", lambda: client)
    ai._CACHE.clear()


def test_unavailable_returns_none(monkeypatch):
    _patch(monkeypatch, _FakeClient(key=""))          # no key
    assert ai.recommend_meetup(DEALS, "Crew") is None
    assert ai.city_vibe("Vienna", "Austria", 3) is None


def test_recommend_uses_only_real_numbers(monkeypatch):
    fake = _FakeClient()
    _patch(monkeypatch, fake)
    out = ai.recommend_meetup(DEALS, "Weekend Crew")
    assert out == "Go with Vienna - cheapest and fairest."
    prompt = fake.calls[0]["user"]
    # Real figures present in the digest
    assert "Vienna" in prompt and "Budapest" in prompt
    assert "€142" in prompt and "€158" in prompt
    assert "spread €20" in prompt          # 60-40 fairness spread, computed
    # System prompt forbids fabrication
    sysmsg = fake.calls[0]["system"].lower()
    assert "only the numbers" in sysmsg or "never invent" in sysmsg


def test_recommend_caches(monkeypatch):
    fake = _FakeClient()
    _patch(monkeypatch, fake)
    ai.recommend_meetup(DEALS, "Crew")
    ai.recommend_meetup(DEALS, "Crew")          # identical → cache hit
    assert len(fake.calls) == 1, "second identical call should hit cache"


def test_recommend_empty_deals_none(monkeypatch):
    _patch(monkeypatch, _FakeClient())
    assert ai.recommend_meetup([], "Crew") is None


def test_ask_returns_plain_answer(monkeypatch):
    fake = _FakeClient()
    _patch(monkeypatch, fake)
    out = ai.ask("how do I add my friend?")
    assert out == "Go with Vienna - cheapest and fairest."
    # The helper's system prompt should describe the bot so answers are on-topic
    sysmsg = fake.calls[0]["system"].lower()
    assert "flight meetup" in sysmsg and "group" in sysmsg
    assert "how do i add my friend?" in fake.calls[0]["user"].lower()


def test_ask_unavailable_and_empty(monkeypatch):
    _patch(monkeypatch, _FakeClient(key=""))
    assert ai.ask("anything") is None
    _patch(monkeypatch, _FakeClient())
    assert ai.ask("   ") is None                # empty question, no LLM call


def test_city_vibe_prompt_and_cache(monkeypatch):
    fake = _FakeClient()
    _patch(monkeypatch, fake)
    a = ai.city_vibe("Vienna", "Austria", 3, "August")
    assert a == "Go with Vienna - cheapest and fairest."
    assert "Vienna" in fake.calls[0]["user"] and "3 nights" in fake.calls[0]["user"]
    ai.city_vibe("Vienna", "Austria", 3, "August")   # cache
    assert len(fake.calls) == 1
