
"""
Replaceable LLM provider for the hospital prototype.

Initial provider: Groq GPT-OSS 20B.

Uses an OpenAI-compatible Chat Completions endpoint.
No patient database access or chat storage occurs here.
"""

import os
from dataclasses import dataclass

import httpx


DEFAULT_SYSTEM_PROMPT = """
You are a patient portal navigation assistant for a fictional
hospital demonstration application.

Help with general navigation and nonclinical questions.

Do not diagnose, recommend treatments, give medication doses,
or invent procedure-preparation instructions.

If approved medical instructions are unavailable, explain
that you cannot verify the answer and direct the patient
to their clinical team.

Do not claim to have accessed appointments, medical records,
or hospital documents unless verified information was
explicitly provided to you.
""".strip()


class LLMProviderError(Exception):
    """Safe, user-displayable model service error."""


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    base_url: str
    api_key: str


PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-20b",
        "key_env": "GROQ_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "key_env": "OPENAI_API_KEY",
    },
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "llama3.2",
        "key_env": None,
    },
}


def get_llm_settings() -> LLMSettings:
    provider = os.getenv(
        "LLM_PROVIDER",
        "groq",
    ).strip().lower()

    if provider not in PROVIDERS:
        raise LLMProviderError(
            "Unsupported LLM provider configuration."
        )

    defaults = PROVIDERS[provider]

    model = os.getenv(
        "LLM_MODEL",
        defaults["model"],
    ).strip()

    base_url = os.getenv(
        "LLM_BASE_URL",
        defaults["base_url"],
    ).strip().rstrip("/")

    key_env = defaults["key_env"]

    if key_env is None:
        api_key = "ollama"
    else:
        api_key = os.getenv(
            key_env,
            "",
        ).strip()

    if not model:
        raise LLMProviderError(
            "LLM model is not configured."
        )

    if not api_key:
        raise LLMProviderError(
            "LLM API key is not configured."
        )

    # Require encrypted connections for hosted providers.
    if provider != "ollama" and not base_url.startswith(
        "https://"
    ):
        raise LLMProviderError(
            "Hosted LLM endpoints must use HTTPS."
        )

    return LLMSettings(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )


def generate_llm_reply(
    message: str,
    *,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> str:
    """
    Generate a response using the configured provider.

    This function sends only the supplied prompt and message.
    It does not access the patient's records.

    Medical safety checks must also be enforced by the
    calling service before and after model generation.
    """

    if not isinstance(message, str):
        raise ValueError("Message must be a string.")

    message = message.strip()

    if not message or len(message) > 2000:
        raise ValueError(
            "Message must contain 1 to 2000 characters."
        )

    settings = get_llm_settings()

    payload = {
        "model": settings.model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": message,
            },
        ],
        "temperature": 0.2,
        "max_completion_tokens": 700,
        "stream": False,
    }

    try:
        with httpx.Client(
            timeout=30.0,
            follow_redirects=False,
        ) as client:
            response = client.post(
                f"{settings.base_url}/chat/completions",
                headers={
                    "Authorization": (
                        f"Bearer {settings.api_key}"
                    ),
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code in (401, 403):
                raise LLMProviderError(
                    "AI provider authentication failed."
                )

            if response.status_code == 429:
                raise LLMProviderError(
                    "AI request limit reached. "
                    "Please try again later."
                )

            if response.status_code >= 400:
                raise LLMProviderError(
                    "The AI provider could not process "
                    "the request."
                )

            data = response.json()

    except httpx.TimeoutException as exc:
        raise LLMProviderError(
            "The AI service timed out."
        ) from exc

    except httpx.RequestError as exc:
        raise LLMProviderError(
            "The AI service is temporarily unavailable."
        ) from exc

    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMProviderError(
            "The AI provider returned an invalid response."
        ) from exc

    try:
        reply = data["choices"][0]["message"]["content"]

        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("Empty model response")

        return reply.strip()

    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LLMProviderError(
            "The AI provider returned no usable answer."
        ) from exc
