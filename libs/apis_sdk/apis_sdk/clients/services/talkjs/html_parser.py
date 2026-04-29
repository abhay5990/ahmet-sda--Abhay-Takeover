"""
TalkJS HTML response parser.

TalkJS embeds state data in HTML as: JSON.parse("...escaped json...")
This module extracts and parses that embedded JSON.
"""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json_from_html(html_content: str) -> dict[str, Any] | None:
    """Extract embedded JSON data from a TalkJS HTML response.

    TalkJS returns HTML pages with a <script> tag containing::

        JSON.parse("...escaped json string...")

    This function finds that pattern and parses the JSON payload.

    Returns:
        Parsed dict, or None if extraction fails.
    """
    # Find JSON.parse("...") pattern in script tags
    # Double-quote variant
    match = re.search(
        r'JSON\.parse\(\s*"((?:[^"\\]|\\.)*)"\s*\)',
        html_content,
        re.DOTALL,
    )
    if not match:
        # Single-quote variant
        match = re.search(
            r"JSON\.parse\(\s*'((?:[^'\\]|\\.)*)'\s*\)",
            html_content,
            re.DOTALL,
        )

    if not match:
        return None

    json_str = match.group(1)

    # Method 1: parse the escaped string as a JSON string literal, then parse the result
    try:
        data = json.loads(f'"{json_str}"')
        if isinstance(data, str):
            data = json.loads(data)
        return data  # type: ignore[return-value]
    except (json.JSONDecodeError, TypeError):
        pass

    # Method 2: manual escape handling
    try:
        temp = json_str.replace("\\\\", "\x00DBLBACK\x00")
        temp = temp.replace('\\"', '"')
        temp = temp.replace("\x00DBLBACK\x00", "\\")
        return json.loads(temp)  # type: ignore[return-value]
    except (json.JSONDecodeError, TypeError):
        return None
