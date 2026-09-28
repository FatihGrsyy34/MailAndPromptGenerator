"""Gemini sarmalayıcı. Pipeline'lar yalnızca `generate` ve `embed` kullanır; testlerde sahte bir LLM verilebilir."""
from __future__ import annotations

import time
from typing import Protocol, TypeVar

from pydantic import BaseModel

from .config import Config, get_api_key

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLMLike(Protocol):
    def generate(self, *, tier: str, system: str, user: str, schema: type[T] | None = None) -> T | str: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class GeminiLLM:
    RETRY_CODES = {429, 500, 502, 503, 504}

    def __init__(self, config: Config, api_key: str | None = None, rounds: int = 3, timeout_s: int = 30):
        from google import genai
        from google.genai import types

        key = api_key or get_api_key()
        if not key:
            raise LLMError("Gemini API anahtarı bulunamadı. `pg setkey` ile kaydedin ya da GEMINI_API_KEY tanımlayın.")
        self.config = config
        # SDK'nın kendi tekrar denemesini kapatıyoruz; tekrar/yedek model mantığı aşağıda ve daha hızlı
        self.client = genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=timeout_s * 1000, retry_options=types.HttpRetryOptions(attempts=1)))
        self.rounds = rounds
        self.calls: list[dict] = []  # iz: hangi adım hangi modelle ne kadar sürdü
        self._cooldown: dict[str, float] = {}  # kotası dolan model → tekrar denenebileceği an
        self._no_thinking: set[str] = set()  # thinking_level desteklemeyen modeller

    def _gen_config(self, tier: str, system: str, schema: type[BaseModel] | None, thinking: bool = True):
        from google.genai import types

        kwargs: dict = {
            "system_instruction": system,
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        level = self.config.thinking(tier)
        if level and thinking:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=level)
        if schema is not None:
            kwargs["response_mime_type"] = "application/json"
            kwargs["response_schema"] = schema
        return types.GenerateContentConfig(**kwargs)

    def _candidates(self, tier: str) -> list[str]:
        primary = self.config.model(tier)
        fallbacks = self.config.models.get(f"{tier}_fallbacks", []) or []
        models = list(dict.fromkeys([primary, *fallbacks]))
        now = time.time()
        ready = [m for m in models if self._cooldown.get(m, 0) <= now]
        return ready or models  # hepsi beklemedeyse yine de dene

    def _note_quota(self, model: str, e: Exception) -> None:
        text = str(e)
        # Günlük kota dolduysa bu oturumda o modeli bir saat atla; dakikalık sınırda bir dakika
        self._cooldown[model] = time.time() + (3600 if "PerDay" in text else 60)

    HEDGE_AFTER = {"quality": 7.0, "fast": 4.0}  # bu kadar saniyede yanıt yoksa sıradaki modeli paralel başlat

    def _attempt(self, model: str, tier: str, system: str, user: str, schema):
        """Tek model denemesi. Döner: ("ok", sonuç) | ("retry", hata) | ("fatal", hata)."""
        from google.genai import errors

        cfg = self._gen_config(tier, system, schema, thinking=model not in self._no_thinking)
        start = time.perf_counter()
        try:
            resp = self.client.models.generate_content(model=model, contents=user, config=cfg)
        except errors.APIError as e:
            code = getattr(e, "code", None)
            if code == 429:
                self._note_quota(model, e)
                return "retry", e
            if code == 400 and "thinking" in str(e).lower() and model not in self._no_thinking:
                self._no_thinking.add(model)  # bu model düşünme ayarını desteklemiyor: ayarsız tekrar denenir
                return "retry", e
            if code == 404:
                self._cooldown[model] = time.time() + 86400
                return "retry", e
            if code in (500, 502, 503, 504):
                self._cooldown[model] = time.time() + 30  # yoğun model: kısa süre dinlendir, sıradakine geç
                return "retry", e
            if code in self.RETRY_CODES:
                return "retry", e
            return "fatal", e
        except Exception as e:  # zaman aşımı, ağ hatası
            return "retry", e
        elapsed = round(time.perf_counter() - start, 2)
        if schema is None:
            self.calls.append({"model": model, "tier": tier, "seconds": elapsed})
            return "ok", (resp.text or "").strip()
        parsed = getattr(resp, "parsed", None)
        if not isinstance(parsed, schema):
            try:
                parsed = schema.model_validate_json(resp.text or "")
            except Exception as e:
                return "retry", e  # bozuk JSON
        self.calls.append({"model": model, "tier": tier, "seconds": elapsed})
        return "ok", parsed

    def generate(self, *, tier: str, system: str, user: str, schema: type[T] | None = None) -> T | str:
        """Gemini'de aralıklı 503 (yoğunluk) ve düşük ücretsiz kotalar (429) sık. Modeller arasında döner; bir model
        HEDGE_AFTER saniyede yanıt vermezse aynı isteği sıradakine de paralel gönderir, ilk başarılı sonucu kullanır."""
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

        queue = [m for _ in range(self.rounds) for m in self._candidates(tier)]
        hedge_after = self.HEDGE_AFTER.get(tier, 6.0)
        last_error: Exception | None = None
        ex = ThreadPoolExecutor(max_workers=4)
        pending: dict = {}

        def launch() -> bool:
            while queue:
                model = queue.pop(0)
                if self._cooldown.get(model, 0) > time.time() and any(self._cooldown.get(m, 0) <= time.time() for m in queue):
                    continue  # kotası dolmuş; daha uygun bir aday var
                pending[ex.submit(self._attempt, model, tier, system, user, schema)] = model
                return True
            return False

        try:
            launch()
            while pending:
                done, _ = wait(list(pending), timeout=hedge_after, return_when=FIRST_COMPLETED)
                if not done:
                    if len(pending) < 2:
                        launch()  # yavaş: paralel yedek başlat
                    continue
                for fut in done:
                    model = pending.pop(fut)
                    status, value = fut.result()
                    if status == "ok":
                        return value
                    last_error = value
                    if status == "fatal":
                        raise LLMError(self._friendly(value, model)) from value
                if not pending and not launch():  # düşen denemenin yerine tek bir yedek (kota israfı olmasın)
                    break
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        raise LLMError(self._friendly(last_error, "tüm modeller"))

    @staticmethod
    def _friendly(e: Exception | None, model: str) -> str:
        code = getattr(e, "code", None)
        if code in (401, 403) or (code == 400 and "API key" in str(e)):
            return "API anahtarı geçersiz ya da yetkisiz. `pg setkey` ile yeniden kaydedin."
        if code == 429:
            return "Gemini kota sınırına ulaşıldı. Biraz bekleyip tekrar deneyin."
        if code in (500, 502, 503, 504):
            return "Gemini şu an yoğun, yedek modeller de yanıt vermedi. Birkaç saniye sonra tekrar deneyin."
        if e is not None and "timed out" in str(e).lower():
            return "Gemini zamanında yanıt vermedi. İnternet bağlantınızı kontrol edip tekrar deneyin."
        return f"Gemini hatası ({model}): {str(e)[:300]}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        model = self.config.model("embedding")
        for i in range(0, len(texts), 50):
            resp = self.client.models.embed_content(model=model, contents=texts[i : i + 50])
            out.extend(e.values for e in resp.embeddings)
        return out

    def list_models(self) -> list[str]:
        from google.genai import errors

        try:
            models = list(self.client.models.list())
        except errors.APIError as e:
            raise LLMError(f"Gemini'ye bağlanılamadı ({getattr(e, 'code', '?')}). API anahtarını kontrol edin: `pg setkey`") from e
        names = []
        for m in models:
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" in actions or "embedContent" in actions:
                names.append(m.name.removeprefix("models/"))
        return sorted(names)
