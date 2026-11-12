
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.llm_provider import (
    generate_llm_reply,
    LLMProviderError,
)

from app.routers.medical_documents import (
    require_patient_session,
)

from app.routers.appointments import (
    check_request_origin,
)


router = APIRouter(
    prefix="/patient/ai",
    tags=["Patient AI Assistant"],
)


# ============================================================
# REQUEST AND RESPONSE
# ============================================================

class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=2000,
    )


class ChatResponse(BaseModel):
    reply: str
    intent: str
    requires_human: bool
    sources: list[str]


# ============================================================
# SAFETY CLASSIFICATION
# ============================================================

EMERGENCY_TERMS = (
    "chest pain",
    "heart attack",
    "stroke",
    "cannot breathe",
    "can't breathe",
    "difficulty breathing",
    "severe bleeding",
    "medical emergency",
    "unconscious",
    "overdose",
)

MEDICAL_TERMS = (
    "surgery",
    "procedure",
    "colonoscopy",
    "endoscopy",
    "anesthesia",
    "fasting",
    "fast",
    "eat",
    "drink",
    "water",
    "medication",
    "medicine",
    "dosage",
    "dose",
    "symptom",
    "pain",
    "diagnosis",
    "treatment",
    "blood pressure",
    "lab result",
    "pre-op",
    "preoperative",
    "preparation instructions",
    "fever",
    "dizzy",
    "nausea",
    "bleeding",
    "infection",
    "prescription",
)


SAFE_LLM_INTENTS = {
    "greeting",
    "appointments",
    "medical_records",
    "clinical_notes",
}


SAFE_REWRITE_PROMPT = """
You are a friendly hospital patient portal navigation assistant.

You will receive a preapproved response about navigating
a fictional hospital portal.

Rewrite it clearly and naturally in one or two sentences.

Rules:
- Preserve the exact factual meaning.
- Do not add facts, features, URLs, or contact details.
- Do not claim to access a patient's records.
- Do not add medical advice or clinical instructions.
- Do not mention diagnoses, treatment, or medication.
- If the text is already concise, keep it close to the original.
- Return only the rewritten response.
""".strip()


# ============================================================
# APPROVED RESPONSES
# ============================================================

def generate_safe_response(message: str) -> ChatResponse:
    question = message.strip().casefold()

    # Emergency checks take priority.
    if any(term in question for term in EMERGENCY_TERMS):
        return ChatResponse(
            reply=(
                "If you may be experiencing a medical "
                "emergency, call 911 or your local "
                "emergency number immediately. "
                "This chat cannot provide emergency care."
            ),
            intent="emergency",
            requires_human=True,
            sources=[],
        )

    # Medical questions must not receive unverified
    # model-generated instructions.
    if any(term in question for term in MEDICAL_TERMS):
        return ChatResponse(
            reply=(
                "I can help find approved hospital "
                "instructions, but that knowledge base "
                "is not connected yet. I cannot confirm "
                "medical or procedure-specific instructions "
                "from this chat. Please follow your "
                "care team's written instructions or "
                "contact the hospital for clarification."
            ),
            intent="medical_guidance",
            requires_human=True,
            sources=[],
        )

    if "clinical note" in question or "doctor note" in question:
        return ChatResponse(
            reply=(
                "Clinical notes that your doctor has "
                "signed and released can be viewed "
                "through your Patient Portal."
            ),
            intent="clinical_notes",
            requires_human=False,
            sources=[],
        )

    if "appointment" in question or "schedule" in question:
        return ChatResponse(
            reply=(
                "You can review your appointments "
                "through the Patient Portal's "
                "appointments section. "
                "I cannot retrieve your personal "
                "appointment details yet."
            ),
            intent="appointments",
            requires_human=False,
            sources=[],
        )

    if any(
        term in question
        for term in (
            "medical record",
            "document",
            "upload",
            "pdf",
        )
    ):
        return ChatResponse(
            reply=(
                "Open Medical Records in your Patient "
                "Portal to access available records "
                "and uploaded documents."
            ),
            intent="medical_records",
            requires_human=False,
            sources=[],
        )

    if question in (
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
    ):
        return ChatResponse(
            reply=(
                "Hello! I can help you navigate "
                "appointments, medical records, "
                "and released clinical notes."
            ),
            intent="greeting",
            requires_human=False,
            sources=[],
        )

    return ChatResponse(
        reply=(
            "I don't have verified information "
            "to answer that question yet. "
            "You can ask about appointments, "
            "medical records, or clinical notes. "
            "For medical questions, contact "
            "your care team."
        ),
        intent="unsupported",
        requires_human=True,
        sources=[],
    )


# ============================================================
# GROQ INTEGRATION
# ============================================================

def generate_patient_ai_response(message: str) -> ChatResponse:
    """
    First apply local safety rules.

    Only approved navigation responses are sent
    to the LLM for rewording.

    The original patient message and any patient
    records are NOT sent to the model.

    Unsupported and medical questions receive
    local fallback responses.
    """

    approved = generate_safe_response(message)

    # Never use the general LLM for medical,
    # emergency, or unsupported requests.
    if approved.intent not in SAFE_LLM_INTENTS:
        return approved

    try:
        ai_reply = generate_llm_reply(
            approved.reply,
            system_prompt=SAFE_REWRITE_PROMPT,
        )

        # Basic output validation.
        # More extensive output checks will be
        # added before expanding AI capabilities.
        if not ai_reply or len(ai_reply) > 1200:
            return approved

        return ChatResponse(
            reply=ai_reply,
            intent=approved.intent,
            requires_human=False,
            sources=[],
        )

    except LLMProviderError:
        # If Groq is unavailable or rate-limited,
        # keep the patient navigation usable.
        return approved


# ============================================================
# AUTHENTICATED PATIENT AI ENDPOINT
# ============================================================

@router.post(
    "/chat",
    response_model=ChatResponse,
)
def patient_ai_chat(
    request: ChatRequest,
    user: dict = Depends(require_patient_session),
    _origin=Depends(check_request_origin),
):
    """
    Patient-only AI chat.

    Authentication:
        Existing patient session validation.

    CSRF:
        Existing request-origin validation.

    LLM:
        Groq through the provider adapter.

    Current restrictions:
        No patient medical records sent to Groq.
        No raw patient messages sent to Groq.
        No AI-generated medical instructions.
        No stored chat history.
    """

    return generate_patient_ai_response(
        request.message
    )
