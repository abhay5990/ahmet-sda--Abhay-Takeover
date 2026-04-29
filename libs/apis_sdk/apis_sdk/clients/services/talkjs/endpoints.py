"""
TalkJS API endpoint constants.
"""


class TalkJsEndpoints:
    """TalkJS API endpoint URL templates."""

    BASE = "https://app.talkjs.com"

    # Chatbox (returns HTML with embedded JSON — messages for a conversation)
    CHATBOX = "/app/{app_id}/user/{user_id}/chatbox/{conversation_id}"

    # Inbox (returns HTML with embedded JSON — conversation list)
    INBOX = "/app/{app_id}/user/{user_id}/inbox/chats"

    # Send message
    SAY = "/api/v0/{app_id}/say/{conversation_id}/"

    # Boken (auth token)
    BOKEN = "/api/v0/{app_id}/bokens/{user_id}"

    @classmethod
    def chatbox(cls, app_id: str, user_id: str, conversation_id: str) -> str:
        return f"{cls.BASE}{cls.CHATBOX.format(app_id=app_id, user_id=user_id, conversation_id=conversation_id)}"

    @classmethod
    def inbox(cls, app_id: str, user_id: str) -> str:
        return f"{cls.BASE}{cls.INBOX.format(app_id=app_id, user_id=user_id)}"

    @classmethod
    def say(cls, app_id: str, conversation_id: str) -> str:
        return f"{cls.BASE}{cls.SAY.format(app_id=app_id, conversation_id=conversation_id)}"

    @classmethod
    def boken(cls, app_id: str, user_id: str) -> str:
        return f"{cls.BASE}{cls.BOKEN.format(app_id=app_id, user_id=user_id)}"
