from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
import json
import os
import sys

import aiohttp


def safe_print(msg: str) -> None:
    """Print safely on Windows terminals that may not support every character."""
    try:
        print(msg)
    except UnicodeEncodeError:
        safe_msg = msg.encode(sys.stdout.encoding, errors="ignore").decode(sys.stdout.encoding)
        print(safe_msg)


class TranslationService(ABC):
    @abstractmethod
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_supported_languages(self) -> List[str]:
        raise NotImplementedError

    async def translate_batch(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        translations: List[str] = []
        for text in texts:
            translations.append(await self.translate(text, source_lang, target_lang))
        return translations


class AioHttpTranslationService(TranslationService):
    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=180)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session


def _build_translation_messages(payload: str, source_lang: str, target_lang: str) -> List[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                f"You are a professional, neutral translator.\n\n"
                f"Translation guidelines:\n"
                f"1. Translate from {source_lang} to {target_lang} naturally and fluently.\n"
                f"2. Keep proper nouns, brand names, product names, and technical terms in their original form if they are commonly used in {target_lang}.\n"
                f"3. Maintain the original tone and style.\n"
                f"4. Preserve layout markers such as line breaks, bullets, numbering, emoji, and leading symbols.\n"
                f"5. Do not add explanations, notes, glosses, or parenthetical original terms unless they already exist in the source text.\n"
                f"6. Do not add new line breaks inside a paragraph; preserve only the source paragraph breaks.\n"
                f"7. Return only the translated text unless the user explicitly asks for JSON."
            ),
        },
        {"role": "user", "content": payload},
    ]


class DeepLService(AioHttpTranslationService):
    def __init__(self) -> None:
        super().__init__()
        self.api_key = os.getenv("DEEPL_API_KEY")
        self.base_url = "https://api-free.deepl.com/v2/translate"

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not self.api_key:
            raise ValueError("DeepL API key not configured")

        session = await self._get_session()
        data = {
            "auth_key": self.api_key,
            "text": text,
            "source_lang": source_lang.upper(),
            "target_lang": target_lang.upper(),
        }
        async with session.post(self.base_url, data=data) as response:
            if response.status != 200:
                raise Exception(f"DeepL API error: {response.status}")
            result = await response.json()
            return result["translations"][0]["text"]

    def get_supported_languages(self) -> List[str]:
        return ["en", "zh", "ja", "ko", "fr", "de", "es", "ru"]


class GoogleTranslateService(AioHttpTranslationService):
    def __init__(self) -> None:
        super().__init__()
        self.api_key = os.getenv("GOOGLE_TRANSLATE_API_KEY")
        self.base_url = "https://translation.googleapis.com/language/translate/v2"

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not self.api_key:
            raise ValueError("Google Translate API key not configured")

        session = await self._get_session()
        params = {
            "key": self.api_key,
            "q": text,
            "source": source_lang,
            "target": target_lang,
        }
        async with session.get(self.base_url, params=params) as response:
            if response.status != 200:
                raise Exception(f"Google API error: {response.status}")
            result = await response.json()
            return result["data"]["translations"][0]["translatedText"]

    def get_supported_languages(self) -> List[str]:
        return ["en", "zh", "ja", "ko", "fr", "de", "es", "ru"]


class OpenAIService(AioHttpTranslationService):
    def __init__(self) -> None:
        super().__init__()
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = "https://api.openai.com/v1/chat/completions"

    async def _request_completion(self, messages: List[Dict[str, str]]) -> str:
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        session = await self._get_session()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        data = {
            "model": "gpt-4o",
            "messages": messages,
            "temperature": 0.3,
        }
        async with session.post(self.base_url, headers=headers, json=data) as response:
            if response.status != 200:
                raise Exception(f"OpenAI API error: {response.status}")
            result = await response.json()
            return result["choices"][0]["message"]["content"].strip()

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        return await self._request_completion(_build_translation_messages(text, source_lang, target_lang))

    def get_supported_languages(self) -> List[str]:
        return ["en", "zh", "ja", "ko", "fr", "de", "es", "ru"]


class OfoxAIService(AioHttpTranslationService):
    def __init__(self) -> None:
        super().__init__()

    def _get_config(self) -> Tuple[str, str, str]:
        api_key = os.getenv("OFOXAI_API_KEY")
        base_url = os.getenv("OFOXAI_BASE_URL", "https://api.ofox.ai/v1").rstrip("/")
        model = os.getenv("OFOXAI_MODEL", "openai/gpt-5.4")
        if not api_key or api_key == "your_ofoxai_api_key_here":
            raise ValueError("OfoxAI API key not configured. Please set OFOXAI_API_KEY in .env file")
        return api_key, base_url, model

    async def _request_completion(
        self,
        messages: List[Dict[str, str]],
        *,
        api_key: str,
        base_url: str,
        model: str,
    ) -> str:
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
        }

        async with session.post(f"{base_url}/chat/completions", headers=headers, json=data) as response:
            if response.status != 200:
                error_text = await response.text()
                safe_print(f"[DEBUG] API error {response.status}: {error_text}")
                raise Exception(f"OfoxAI API error: {response.status} - {error_text}")
            result = await response.json()
            translated_text = result["choices"][0]["message"]["content"].strip()
            safe_translated = translated_text.encode("utf-8", errors="ignore").decode("utf-8")
            safe_print(
                f"[DEBUG] OfoxAIService.translate success: result_length={len(translated_text)}, "
                f"first_50_chars={safe_translated[:50]}"
            )
            return translated_text

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        api_key, base_url, model = self._get_config()
        safe_print(
            f"[DEBUG] OfoxAIService.translate called: text_length={len(text)}, "
            f"source={source_lang}, target={target_lang}"
        )
        messages = _build_translation_messages(text, source_lang, target_lang)
        return await self._request_completion(messages, api_key=api_key, base_url=base_url, model=model)

    async def translate_batch(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        if not texts:
            return []

        api_key, base_url, model = self._get_config()
        payload = json.dumps(
            [{"id": index, "text": text} for index, text in enumerate(texts)],
            ensure_ascii=False,
        )
        messages = _build_translation_messages(
            (
                "Translate every item in the JSON array.\n"
                "Return JSON only in exactly this shape: "
                '[{"id":0,"translatedText":"..."}, ...].\n'
                "Do not omit any item. Keep ids unchanged.\n"
                f"Input JSON:\n{payload}"
            ),
            source_lang,
            target_lang,
        )
        raw_response = await self._request_completion(
            messages,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )

        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise Exception(f"Batch translation returned invalid JSON: {exc}") from exc

        if not isinstance(parsed, list):
            raise Exception("Batch translation response must be a JSON array")

        translations_by_id: Dict[int, str] = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            translated_text = item.get("translatedText")
            if isinstance(item_id, int) and isinstance(translated_text, str):
                translations_by_id[item_id] = translated_text.strip()

        if len(translations_by_id) != len(texts):
            raise Exception("Batch translation response is missing items")

        return [translations_by_id[index] for index in range(len(texts))]

    def get_supported_languages(self) -> List[str]:
        return ["en", "zh", "ja", "ko", "fr", "de", "es", "ru"]


class MockTranslationService(TranslationService):
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if source_lang == target_lang:
            return text

        mock_translations = {
            "Hello": {"zh": "你好", "ja": "こんにちは", "ko": "안녕하세요"},
            "World": {"zh": "世界", "ja": "世界", "ko": "세계"},
            "Welcome": {"zh": "欢迎", "ja": "ようこそ", "ko": "환영합니다"},
            "Thank you": {"zh": "谢谢", "ja": "ありがとうございます", "ko": "감사합니다"},
        }

        for original, translations in mock_translations.items():
            if original in text:
                text = text.replace(original, translations.get(target_lang, f"[{target_lang}: {original}]"))

        if text not in mock_translations:
            text = f"[{target_lang}: {text}]"

        return text

    def get_supported_languages(self) -> List[str]:
        return ["en", "zh", "ja", "ko", "fr", "de", "es", "ru"]


class TranslationServiceFactory:
    _services: Dict[str, TranslationService] = {}

    @classmethod
    def register(cls, name: str, service: TranslationService) -> None:
        cls._services[name] = service

    @classmethod
    def get(cls, name: str = "mock") -> TranslationService:
        return cls._services.get(name) or MockTranslationService()


TranslationServiceFactory.register("mock", MockTranslationService())
TranslationServiceFactory.register("deepl", DeepLService())
TranslationServiceFactory.register("google", GoogleTranslateService())
TranslationServiceFactory.register("openai", OpenAIService())
TranslationServiceFactory.register("ofoxai", OfoxAIService())
