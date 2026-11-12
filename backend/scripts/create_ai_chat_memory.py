
"""
Create SQLite tables for Patient AI Chat Memory.

Stores:
- Patient conversations
- User and assistant messages
- Conversation timestamps

Uses the existing hospital database.
"""

from contextlib import closing

from app.core.database import get_db


def create_ai_chat_tables(conn):
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ai_conversations (
            conversation_id TEXT PRIMARY KEY,

            patient_id TEXT NOT NULL
                REFERENCES patients(patient_id),

            owner_user_id TEXT NOT NULL
                REFERENCES users(user_id),

            title TEXT NOT NULL DEFAULT 'New Chat',

            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ai_chat_messages (
            message_id TEXT PRIMARY KEY,

            conversation_id TEXT NOT NULL
                REFERENCES ai_conversations(conversation_id)
                ON DELETE CASCADE,

            role TEXT NOT NULL
                CHECK (role IN ('user', 'assistant')),

            content TEXT NOT NULL
                CHECK (length(content) > 0),

            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS
            idx_ai_conversations_patient
        ON ai_conversations (
            patient_id,
            updated_at
        );

        CREATE INDEX IF NOT EXISTS
            idx_ai_conversations_owner
        ON ai_conversations (
            owner_user_id,
            updated_at
        );

        CREATE INDEX IF NOT EXISTS
            idx_ai_messages_conversation
        ON ai_chat_messages (
            conversation_id,
            created_at
        );
    """)


def main():
    with closing(get_db()) as conn:
        create_ai_chat_tables(conn)
        conn.commit()

        conversations = conn.execute("""
            SELECT COUNT(*)
            FROM ai_conversations
        """).fetchone()[0]

        messages = conn.execute("""
            SELECT COUNT(*)
            FROM ai_chat_messages
        """).fetchone()[0]

        print("AI Chat Memory tables created successfully.")
        print("Conversations:", conversations)
        print("Messages:", messages)


if __name__ == "__main__":
    main()
