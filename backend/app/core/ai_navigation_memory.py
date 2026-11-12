"""
Local conversational memory for patient portal navigation.

Reads:
    app/core/ai_navigation_text.json

Only resolves simple navigation follow-ups.
Does not send conversation history to external LLMs.
"""

import json
import re
from pathlib import Path


CONFIG_PATH = Path(__file__).with_name(
    "ai_navigation_text.json"
)

PROTECTED_MEDICAL_CUES = (
    "emergency",
    "911",
    "chest pain",
    "trouble breathing",
    "bleeding",
    "medication",
    "dosage",
    "dose",
    "diagnosis",
    "treatment",
    "symptom",
    "suicide",
)


def normalize(text):
    return " ".join(
        re.findall(
            r"[a-z0-9]+(?:'[a-z0-9]+)?",
            str(text).casefold(),
        )
    )


def contains_phrase(text, phrase):
    phrase = normalize(phrase)

    if not phrase:
        return False

    pattern = (
        r"(?<!\w)"
        + re.escape(phrase)
        + r"s?(?!\w)"
    )

    return re.search(pattern, text) is not None


def contains_any(text, phrases):
    return any(
        isinstance(phrase, str)
        and contains_phrase(text, phrase)
        for phrase in phrases
    )


def load_navigation_config():
    try:
        with CONFIG_PATH.open(
            "r",
            encoding="utf-8",
        ) as file:
            config = json.load(file)

    except (OSError, UnicodeError, json.JSONDecodeError):
        return None

    if not isinstance(config, dict):
        return None

    required = {
        "follow_up_phrases": list,
        "navigation_cues": list,
        "medical_safety_cues": list,
        "topics": dict,
    }

    for key, expected_type in required.items():
        if not isinstance(config.get(key), expected_type):
            return None

    return config


def resolve_navigation_followup(
    conn,
    conversation_id,
    message,
):
    """
    Returns (topic, reply) for safe navigation follow-ups.
    Returns None when context is missing or uncertain.

    Caller must verify patient ownership before calling.
    """

    config = load_navigation_config()

    if config is None:
        return None

    current = normalize(message)

    followups = {
        normalize(phrase)
        for phrase in config["follow_up_phrases"]
        if isinstance(phrase, str)
    }

    if current not in followups:
        return None

    medical_cues = (
        list(PROTECTED_MEDICAL_CUES)
        + config["medical_safety_cues"]
    )

    if contains_any(current, medical_cues):
        return None

    previous_messages = conn.execute(
        """
        SELECT content
        FROM ai_chat_messages
        WHERE conversation_id = ?
          AND role = 'user'
        ORDER BY created_at DESC, rowid DESC
        LIMIT 12
        """,
        (conversation_id,),
    ).fetchall()

    for row in previous_messages:
        previous = normalize(row["content"])

        if previous in followups:
            continue

        if contains_any(previous, medical_cues):
            return None

        matching_topics = []

        for topic, details in config["topics"].items():
            if not isinstance(details, dict):
                return None

            keywords = details.get("keywords")

            if not isinstance(keywords, list):
                return None

            if contains_any(previous, keywords):
                matching_topics.append(topic)

        if len(matching_topics) != 1:
            return None

        if not contains_any(
            previous,
            config["navigation_cues"],
        ):
            return None

        topic = matching_topics[0]
        reply = config["topics"][topic].get("reply")

        if not isinstance(reply, str) or not reply.strip():
            return None

        return topic, reply.strip()

    return None
