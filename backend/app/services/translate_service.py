from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import os
import sys
import aiohttp
from openai import AsyncOpenAI


def safe_print(msg: str):
    """安全地打印，避免 Windows 下 emoji 编码问题"""
    try:
        print(msg)
    except UnicodeEncodeError:
        # Windows GBK 编码问题，忽略无法编码的字符
        safe_msg = msg.encode(sys.stdout.encoding, errors='ignore').decode(sys.stdout.encoding)
        print(safe_msg)

class TranslationService(ABC):
    @abstractmethod
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        pass
    
    @abstractmethod
    def get_supported_languages(self) -> List[str]:
        pass

class DeepLService(TranslationService):
    def __init__(self):
        self.api_key = os.getenv("DEEPL_API_KEY")
        self.base_url = "https://api-free.deepl.com/v2/translate"
    
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not self.api_key:
            raise ValueError("DeepL API key not configured")
        
        async with aiohttp.ClientSession() as session:
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

class GoogleTranslateService(TranslationService):
    def __init__(self):
        self.api_key = os.getenv("GOOGLE_TRANSLATE_API_KEY")
        self.base_url = "https://translation.googleapis.com/language/translate/v2"
    
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not self.api_key:
            raise ValueError("Google Translate API key not configured")
        
        async with aiohttp.ClientSession() as session:
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

class OpenAIService(TranslationService):
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = "https://api.openai.com/v1/chat/completions"
    
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")
        
        messages = [
            {
                "role": "system",
                "content": f"You are a professional, neutral translator.\n\n**Translation Guidelines:**\n1. Translate from {source_lang} to {target_lang} naturally and fluently.\n2. Keep proper nouns, brand names, product names, and technical terms in their original form if they are commonly used in {target_lang}.\n3. Maintain the original tone and style.\n4. Do NOT add any explanations, notes, or extra content.\n5. Return ONLY the translated text."
            },
            {"role": "user", "content": text}
        ]
        
        async with aiohttp.ClientSession() as session:
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
    
    def get_supported_languages(self) -> List[str]:
        return ["en", "zh", "ja", "ko", "fr", "de", "es", "ru"]

class OfoxAIService(TranslationService):
    def __init__(self):
        pass
    
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        api_key = os.getenv("OFOXAI_API_KEY")
        base_url = os.getenv("OFOXAI_BASE_URL", "https://api.ofox.ai/v1")
        model = os.getenv("OFOXAI_MODEL", "openai/gpt-5.4-nano")
        
        if not api_key or api_key == "your_ofoxai_api_key_here":
            raise ValueError("OfoxAI API key not configured. Please set OFOXAI_API_KEY in .env file")
        
        safe_print(f"[DEBUG] OfoxAIService.translate called: text_length={len(text)}, source={source_lang}, target={target_lang}")
        
        messages = [
            {
                "role": "system",
                "content": f"You are a professional, neutral translator.\n\n**Translation Guidelines:**\n1. Translate from {source_lang} to {target_lang} naturally and fluently.\n2. Keep proper nouns, brand names, product names, and technical terms in their original form if they are commonly used in {target_lang}.\n3. Maintain the original tone and style.\n4. Do NOT add any explanations, notes, or extra content.\n5. Return ONLY the translated text."
            },
            {"role": "user", "content": text}
        ]
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
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
                    # 安全地打印日志
                    safe_translated = translated_text.encode('utf-8', errors='ignore').decode('utf-8')
                    safe_print(f"[DEBUG] OfoxAIService.translate success: result_length={len(translated_text)}, first_50_chars={safe_translated[:50]}")
                    return translated_text
        except Exception as e:
            safe_print(f"[DEBUG] OfoxAIService.translate failed: {str(e)}")
            raise
    
    def get_supported_languages(self) -> List[str]:
        return ["en", "zh", "ja", "ko", "fr", "de", "es", "ru"]

class MockTranslationService(TranslationService):
    """Mock service for testing without API keys"""
    
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if source_lang == target_lang:
            return text
        
        mock_translations = {
            "Hello": {"zh": "你好", "ja": "こんにちは", "ko": "안녕하세요"},
            "World": {"zh": "世界", "ja": "世界", "ko": "세계"},
            "Welcome": {"zh": "欢迎", "ja": "ようこそ", "ko": "환영합니다"},
            "Thank you": {"zh": "谢谢", "ja": "ありがとう", "ko": "감사합니다"},
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
    def register(cls, name: str, service: TranslationService):
        cls._services[name] = service
    
    @classmethod
    def get(cls, name: str = "mock") -> TranslationService:
        return cls._services.get(name) or MockTranslationService()

TranslationServiceFactory.register("mock", MockTranslationService())
TranslationServiceFactory.register("deepl", DeepLService())
TranslationServiceFactory.register("google", GoogleTranslateService())
TranslationServiceFactory.register("openai", OpenAIService())
TranslationServiceFactory.register("ofoxai", OfoxAIService())
