
from app.core.ai_appointment_intents import (
    classify_appointment_question,
)

from app.core.ai_appointment_filters import (
    filter_appointments_for_intent,
)

from app.core.ai_appointment_tools import (
    get_upcoming_appointments,
    format_appointments_for_patient,
)


"""
Patient AI conversation memory API.

Features:
- Create conversations
- List previous conversations
- Read conversation messages
- Send messages and save AI responses
- Delete conversations and messages

Every operation is restricted to the authenticated
patient's own account.

Prototype only: use fictional patient data.
"""

from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from pydantic import BaseModel, Field

from app.core.database import get_db

from app.routers.medical_documents import (
    require_patient_session,
)
from app.routers.appointments import (
    check_request_origin,
)
from app.routers.patient_ai import (
    ChatResponse,
    generate_patient_ai_response,
)

from app.core.ai_navigation_memory import (
    resolve_navigation_followup,
    load_navigation_config,
    contains_any,
    PROTECTED_MEDICAL_CUES,
)


router = APIRouter(
    prefix="/patient/ai/conversations",
    tags=["Patient AI Chat Memory"],
)

MAX_MESSAGES_PER_CONVERSATION = 200


def get_booking_navigation_reply(message):
    """Return approved instructions for booking questions."""

    config = load_navigation_config()
    if config is None:
        return None

    words = set(
        "".join(
            char if char.isalnum() else " "
            for char in message.casefold()
        ).split()
    )

    mentions_appointment = bool(
        words & {"appointment", "appointments"}
    )

    mentions_booking = bool(
        words & {"book", "schedule", "make"}
    )

    asks_for_help = bool(
        words & {"how", "where", "new", "another", "can", "want"}
    )

    if not (
        mentions_appointment
        and mentions_booking
        and asks_for_help
    ):
        return None

    medical_cues = (
        list(PROTECTED_MEDICAL_CUES)
        + config["medical_safety_cues"]
    )

    if contains_any(message, medical_cues):
        return None

    appointment_config = config["topics"].get("appointments", {})

    if not isinstance(appointment_config, dict):
        return None

    reply = appointment_config.get("booking_reply")

    if not isinstance(reply, str) or not reply.strip():
        return None

    return reply.strip()




def is_appointment_lookup(message):
    """
    Recognize explicit requests for appointment details.

    Other questions continue through existing safety
    and navigation routing.
    """
    normalized = " ".join(
        message.casefold().strip(" ?!.").split()
    )

    lookup_phrases = {
        "what are my appointments",
        "what appointments do i have",
        "show my appointments",
        "show me my appointments",
        "show my upcoming appointments",
        "show all my upcoming appointments",
        "show all my appointments",
        "show my next appointment",
        "what are my upcoming appointments",
        "do i have any appointments",
        "do i have any upcoming appointments",
        "when is my next appointment",
        "what is my next appointment",
        "when are my appointments",
        "list my appointments",
    }

    return normalized in lookup_phrases



# ============================================================
# MODELS
# ============================================================

class SendMessageRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=2000,
    )


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).isoformat()


def get_owned_conversation(conn, conversation_id, user):
    """
    Find a conversation owned by the current patient.

    Return 404 for missing or unauthorized conversations
    so their existence is not disclosed.
    """

    row = conn.execute("""
        SELECT
            conversation_id,
            title,
            created_at,
            updated_at
        FROM ai_conversations
        WHERE conversation_id = ?
          AND owner_user_id = ?
          AND patient_id = ?
    """, (
        conversation_id,
        user["user_id"],
        user["patient_id"],
    )).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    return row


# ============================================================
# CREATE CONVERSATION
# ============================================================

@router.post("", status_code=201)
def create_conversation(
    user: dict = Depends(require_patient_session),
    _origin=Depends(check_request_origin),
):
    conversation_id = str(uuid4())
    timestamp = now_utc()

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        conn.execute("""
            INSERT INTO ai_conversations (
                conversation_id,
                patient_id,
                owner_user_id,
                title,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            conversation_id,
            user["patient_id"],
            user["user_id"],
            "New Chat",
            timestamp,
            timestamp,
        ))

        conn.commit()

    return {
        "conversation_id": conversation_id,
        "title": "New Chat",
        "created_at": timestamp,
        "updated_at": timestamp,
    }


# ============================================================
# LIST OWN CONVERSATIONS
# ============================================================

@router.get("")
def list_conversations(
    limit: int = Query(default=50, ge=1, le=100),
    user: dict = Depends(require_patient_session),
):
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                conversation_id,
                title,
                created_at,
                updated_at
            FROM ai_conversations
            WHERE owner_user_id = ?
              AND patient_id = ?
            ORDER BY updated_at DESC, rowid DESC
            LIMIT ?
        """, (
            user["user_id"],
            user["patient_id"],
            limit,
        )).fetchall()

    return {
        "conversations": [dict(row) for row in rows],
        "total": len(rows),
    }


# ============================================================
# READ CONVERSATION HISTORY
# ============================================================

@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str,
    user: dict = Depends(require_patient_session),
):
    with closing(get_db()) as conn:
        conversation = get_owned_conversation(
            conn,
            conversation_id,
            user,
        )

        messages = conn.execute("""
            SELECT
                message_id,
                role,
                content,
                created_at
            FROM ai_chat_messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC, rowid ASC
        """, (
            conversation_id,
        )).fetchall()

    return {
        "conversation_id": conversation["conversation_id"],
        "title": conversation["title"],
        "created_at": conversation["created_at"],
        "updated_at": conversation["updated_at"],
        "messages": [dict(row) for row in messages],
    }


# ============================================================
# SEND MESSAGE AND SAVE AI RESPONSE
# ============================================================

@router.post("/{conversation_id}/messages", status_code=201)
def send_conversation_message(
    conversation_id: str,
    request: SendMessageRequest,
    user: dict = Depends(require_patient_session),
    _origin=Depends(check_request_origin),
):
    message = request.message.strip()

    if not message:
        raise HTTPException(
            status_code=422,
            detail="Message cannot be empty",
        )

    # Verify ownership before generating a response.
    with closing(get_db()) as conn:
        get_owned_conversation(
            conn,
            conversation_id,
            user,
        )

    # Reuse the existing safety-aware AI service.
    #
    # That service sends only approved navigation
    # response text to Groq, not the patient's
    # original message or saved chat history.
    with closing(get_db()) as conn:
        memory_result = resolve_navigation_followup(
            conn,
            conversation_id,
            message,
        )

    booking_reply = get_booking_navigation_reply(message)
    appointment_intent = classify_appointment_question(message)

    if booking_reply is not None:
        result = ChatResponse(
            reply=booking_reply,
            intent="appointments",
            requires_human=False,
            sources=[],
        )

    elif is_appointment_lookup(message):
        question = " ".join(
            message.casefold().strip(" ?!.").split()
        )

        next_only = question in {
            "when is my next appointment",
            "what is my next appointment",
            "show my next appointment",
        }

        all_requested = question in {
            "show all my appointments",
            "show all my upcoming appointments",
        }

        # One appointment for "next", up to 20 for "all",
        # and up to 10 for other appointment lookups.
        limit = (
            1 if next_only
            else 20 if all_requested
            else 10
        )

        upcoming = get_upcoming_appointments(
            user["patient_id"],
            limit=limit,
        )

        result = ChatResponse(
            reply=format_appointments_for_patient(upcoming),
            intent="appointments",
            requires_human=False,
            sources=[],
        )

    elif (
        appointment_intent is not None
        and appointment_intent["action"] in {
            "next",
            "upcoming",
            "by_weekday",
            "by_specialty",
        }
    ):
        action = appointment_intent["action"]

        # Retrieve only records belonging to the
        # authenticated patient.
        #
        # Fetch up to 20 for filtered searches.
        # An unfiltered "next" query needs only one.
        limit = (
            1
            if action == "next"
            and not appointment_intent.get("specialty")
            and not appointment_intent.get("weekday")
            else 20
        )

        upcoming = get_upcoming_appointments(
            user["patient_id"],
            limit=limit,
        )

        matching = filter_appointments_for_intent(
            upcoming,
            appointment_intent,
            message,
        )

        if matching:
            reply = format_appointments_for_patient(
                matching
            )

        elif action == "by_weekday":
            reply = (
                "I did not find a matching appointment "
                "among your next 20 upcoming bookings "
                "for that day. Open My Appointments "
                "to review your full schedule."
            )

        elif action == "by_specialty":
            specialty = appointment_intent["specialty"]

            reply = (
                f"I did not find a {specialty} appointment "
                "among your next 20 upcoming bookings. "
                "Open My Appointments to review "
                "your full schedule."
            )

        else:
            reply = format_appointments_for_patient([])

        result = ChatResponse(
            reply=reply,
            intent="appointments",
            requires_human=False,
            sources=[],
        )

    elif memory_result is not None:
        topic, reply = memory_result

        result = ChatResponse(
            reply=reply,
            intent=topic,
            requires_human=False,
            sources=[],
        )
    else:
        result = generate_patient_ai_response(message)

    timestamp = now_utc()

    user_message_id = str(uuid4())
    assistant_message_id = str(uuid4())

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        # Re-check ownership inside the write transaction.
        conversation = get_owned_conversation(
            conn,
            conversation_id,
            user,
        )

        count = conn.execute("""
            SELECT COUNT(*)
            FROM ai_chat_messages
            WHERE conversation_id = ?
        """, (
            conversation_id,
        )).fetchone()[0]

        if count + 2 > MAX_MESSAGES_PER_CONVERSATION:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Conversation message limit reached. "
                    "Please start a new chat."
                ),
            )

        conn.executemany("""
            INSERT INTO ai_chat_messages (
                message_id,
                conversation_id,
                role,
                content,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, [
            (
                user_message_id,
                conversation_id,
                "user",
                message,
                timestamp,
            ),
            (
                assistant_message_id,
                conversation_id,
                "assistant",
                result.reply,
                timestamp,
            ),
        ])

        # Use a category-based title instead of copying
        # potentially sensitive patient text into it.
        title_map = {
            "appointments": "Appointments",
            "medical_records": "Medical Records",
            "clinical_notes": "Clinical Notes",
            "medical_guidance": "Medical Questions",
            "emergency": "Safety Information",
        }

        new_title = (
            title_map.get(result.intent, conversation["title"])
            if conversation["title"] == "New Chat"
            else conversation["title"]
        )

        conn.execute("""
            UPDATE ai_conversations
            SET title = ?,
                updated_at = ?
            WHERE conversation_id = ?
              AND owner_user_id = ?
              AND patient_id = ?
        """, (
            new_title,
            timestamp,
            conversation_id,
            user["user_id"],
            user["patient_id"],
        ))

        conn.commit()

    return {
        "conversation_id": conversation_id,
        "user_message": {
            "message_id": user_message_id,
            "role": "user",
            "content": message,
            "created_at": timestamp,
        },
        "assistant_message": {
            "message_id": assistant_message_id,
            "role": "assistant",
            "content": result.reply,
            "created_at": timestamp,
        },
        "intent": result.intent,
        "requires_human": result.requires_human,
        "sources": result.sources,
    }


# ============================================================
# DELETE CONVERSATION
# ============================================================

@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    user: dict = Depends(require_patient_session),
    _origin=Depends(check_request_origin),
):
    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        get_owned_conversation(
            conn,
            conversation_id,
            user,
        )

        # ON DELETE CASCADE deletes its saved messages.
        conn.execute("""
            DELETE FROM ai_conversations
            WHERE conversation_id = ?
              AND owner_user_id = ?
              AND patient_id = ?
        """, (
            conversation_id,
            user["user_id"],
            user["patient_id"],
        ))

        conn.commit()

    return {
        "deleted": True,
        "conversation_id": conversation_id,
    }
