"""GeminiLLM'in yedek model, paralel yedek (hedging) ve hata mantığı. Gerçek API çağrısı yok."""
import threading
import time

import pytest
from google.genai import errors
from pydantic import BaseModel

from engine.config import load_config
from engine.llm import GeminiLLM, LLMError


class Out(BaseModel):
    text: str


class Resp:
    def __init__(self, text):
        self.text = text
        self.parsed = None


def api_error(code, msg="x"):
    return errors.APIError(code, {"error": {"code": code, "message": msg, "status": "X"}})


class FakeModels:
    def __init__(self, behaviour):
        self.behaviour = behaviour  # model -> list of actions: ("ok", text) | ("err", code) | ("sleep", s, text)
        self.calls = []
        self.lock = threading.Lock()

    def generate_content(self, model, contents, config):
        with self.lock:
            self.calls.append(model)
            action = self.behaviour[model].pop(0) if len(self.behaviour[model]) > 1 else self.behaviour[model][0]
        if action[0] == "err":
            raise api_error(action[1], action[2] if len(action) > 2 else "x")
        if action[0] == "sleep":
            time.sleep(action[1])
            return Resp(action[2])
        return Resp(action[1])


def make(behaviour, quality=("a", "b", "c")):
    cfg = load_config()
    cfg.models = {"quality": quality[0], "quality_fallbacks": list(quality[1:]), "fast": "f", "fast_fallbacks": [],
                  "quality_thinking": "", "fast_thinking": ""}
    llm = object.__new__(GeminiLLM)
    llm.config, llm.rounds, llm.calls = cfg, 2, []
    llm._cooldown, llm._no_thinking = {}, set()
    llm.client = type("C", (), {"models": FakeModels(behaviour)})()
    return llm


def test_falls_back_on_503():
    llm = make({"a": [("err", 503)], "b": [("ok", '{"text": "B"}')], "c": [("ok", '{"text": "C"}')]})
    assert llm.generate(tier="quality", system="s", user="u", schema=Out).text == "B"


def test_quota_429_puts_model_on_cooldown():
    llm = make({"a": [("err", 429, "GenerateRequestsPerDayPerProjectPerModel-FreeTier")], "b": [("ok", '{"text": "B"}')], "c": [("ok", "x")]})
    llm.generate(tier="quality", system="s", user="u", schema=Out)
    assert llm._cooldown["a"] > time.time() + 3000
    llm.generate(tier="quality", system="s", user="u", schema=Out)
    assert llm.client.models.calls.count("a") == 1  # ikinci çağrıda atlandı


def test_hedges_when_primary_is_slow():
    llm = make({"a": [("sleep", 3.0, '{"text": "A"}')], "b": [("ok", '{"text": "B"}')], "c": [("ok", "x")]})
    llm.HEDGE_AFTER = {"quality": 0.2}
    start = time.perf_counter()
    assert llm.generate(tier="quality", system="s", user="u", schema=Out).text == "B"
    assert time.perf_counter() - start < 1.5


def test_fatal_error_raises_friendly_message():
    llm = make({"a": [("err", 403)], "b": [("ok", "x")], "c": [("ok", "x")]})
    with pytest.raises(LLMError, match="API anahtarı"):
        llm.generate(tier="quality", system="s", user="u", schema=Out)


def test_all_busy_gives_busy_message():
    llm = make({"a": [("err", 503)], "b": [("err", 503)], "c": [("err", 503)]})
    with pytest.raises(LLMError, match="yoğun"):
        llm.generate(tier="quality", system="s", user="u", schema=Out)


def test_bad_json_tries_next_model():
    llm = make({"a": [("ok", "not json")], "b": [("ok", '{"text": "B"}')], "c": [("ok", "x")]})
    assert llm.generate(tier="quality", system="s", user="u", schema=Out).text == "B"
