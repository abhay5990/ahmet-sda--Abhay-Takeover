import json

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import models


def _get_fernet():
    key = getattr(settings, 'CREDENTIAL_ENCRYPTION_KEY', None)
    if not key:
        raise ValueError("CREDENTIAL_ENCRYPTION_KEY is not set in settings/environment.")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(data: dict) -> str:
    """Encrypt a dict to a Fernet-encrypted string."""
    f = _get_fernet()
    return f.encrypt(json.dumps(data).encode()).decode()


def decrypt_value(token: str) -> dict:
    """Decrypt a Fernet-encrypted string back to a dict."""
    f = _get_fernet()
    return json.loads(f.decrypt(token.encode()).decode())


class EncryptedJSONField(models.TextField):
    """Django model field that stores JSON data encrypted with Fernet.

    In Python: works with plain dicts.
    In DB: stored as a Fernet-encrypted string (TEXT column).
    """

    description = "Encrypted JSON data"

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return {}
        return decrypt_value(value)

    def get_prep_value(self, value):
        if value is None:
            return None
        if isinstance(value, str):
            # Already encrypted (e.g. from a raw update)
            return value
        return encrypt_value(value)

    def to_python(self, value):
        if isinstance(value, dict):
            return value
        if value is None or value == '':
            return {}
        try:
            return decrypt_value(value)
        except Exception:
            # Could be plain JSON during form input
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return {}

    def value_to_string(self, obj):
        """Used by dumpdata / serialization."""
        value = self.value_from_object(obj)
        return json.dumps(value)


class EncryptedTextField(models.TextField):
    """Django model field that stores a single string value encrypted with Fernet.

    In Python: works with plain strings.
    In DB: stored as a Fernet-encrypted string (TEXT column).
    """

    description = "Encrypted text data"

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return ''
        f = _get_fernet()
        return f.decrypt(value.encode()).decode()

    def get_prep_value(self, value):
        if value is None or value == '':
            return value
        if not isinstance(value, str):
            value = str(value)
        f = _get_fernet()
        return f.encrypt(value.encode()).decode()

    def to_python(self, value):
        if isinstance(value, str):
            try:
                f = _get_fernet()
                return f.decrypt(value.encode()).decode()
            except Exception:
                return value
        return value or ''

    def value_to_string(self, obj):
        """Used by dumpdata / serialization."""
        return self.value_from_object(obj)
