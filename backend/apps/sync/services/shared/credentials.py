"""Shared credential text parser for all providers.

Parses free-text credential strings into structured data.
Handles multiple formats found across Gameboost, Eldorado, and others:

  - Labeled lines:    "Login: xxx"  /  "Password: yyy"
  - Arrow format:     "Device ID -> xxx"  /  "E-mail -> yyy"
  - Mail label:       "mail: xxx"  /  "mail password: yyy"  /  "epic password: zzz"
  - Section headers:  "Epic Games Details:\\n\\temail : pass"
  - Colon separated:  "email@x.com:password"
  - Tab separated:    "email@x.com\\tpassword"
  - Newline pairs:    "email@x.com\\npassword"

Usage:
    from apps.sync.services.shared.credentials import parse_credentials_text

    result = parse_credentials_text("Login: user@mail.com\\nPassword: abc123")
    result.login       # "user@mail.com"
    result.password    # "abc123"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ParsedCredentials:
    """Structured credential data extracted from free text."""

    login: str = ''
    password: str = ''
    email: str = ''
    email_password: str = ''
    email_login_link: str = ''
    security_email: str = ''
    security_email_password: str = ''

    # Raw extras that didn't map to known fields
    extras: dict[str, str] = field(default_factory=dict)


# ── Label mappings ──────────────────────────────────────────────────
# Maps normalized label → field_name
# First match wins when multiple labels map to the same field.

_LABEL_MAP: dict[str, str] = {
    # Login
    'login': 'login',
    'username': 'login',
    'account': 'login',
    'id': 'login',                 # "ID: username" — standalone id label
    'device id': 'login',
    'account login': 'login',
    # Platform/game name inline labels — these appear as "Epic: user@x.com" style.
    # The section-header regex handles bare "epic\n" lines (no value on same line);
    # these entries handle the inline "Epic: value" colon format.
    'epic': 'login',
    'riot': 'login',
    'steam': 'login',
    'ubi': 'login',
    'ubisoft': 'login',
    'valorant': 'login',
    'fortnite': 'login',
    'roblox': 'login',
    'apex': 'login',
    'cod': 'login',
    'pubg': 'login',
    'genshin': 'login',
    'minecraft': 'login',
    'epic games': 'login',
    'epic mail': 'login',
    'supercell id': 'login',
    'riot id': 'login',
    'steam id': 'login',
    'psn id': 'login',
    'psn id and mail': 'login',
    'psn username': 'login',
    'xbox id': 'login',
    'xbox username': 'login',
    'rockstar id': 'login',
    'account mail': 'login',
    'mail adress': 'login',       # common typo for "mail address"
    'mail address': 'login',
    # Password
    'pass': 'password',
    'password': 'password',
    'device password': 'password',
    'account password': 'password',
    'epic password': 'password',
    'epic p': 'password',
    'epic pw': 'password',
    'epic games password': 'password',
    'epic games & mail password': 'password',
    'psn password': 'password',
    'xbox password': 'password',
    'mail and psn password': 'password',
    'riot account password': 'password',
    'roblox account password': 'password',
    'supercell id password': 'password',
    'steam password': 'password',
    'rockstar password': 'password',
    'rockstar account password': 'password',
    # Email
    'email': 'email',
    'e-mail': 'email',
    'mail': 'email',
    'email login': 'email',
    # Email password
    'email password': 'email_password',
    'e-mail password': 'email_password',
    'email pass': 'email_password',
    'mail password': 'email_password',
    'mail p': 'email_password',
    'mail pw': 'email_password',
    'mail pass': 'email_password',
    'mail pasword': 'email_password',
    'e mail password': 'email_password',
    # Email login link
    'email login link': 'email_login_link',
    'e-mail login link': 'email_login_link',
    'email sign in link': 'email_login_link',
    'e-mail sign in link': 'email_login_link',
    'mail login link': 'email_login_link',
    'mail login': 'email_login_link',
    'mail log in': 'email_login_link',
    'mail sign in link': 'email_login_link',
    'mail sign-in': 'email_login_link',
    'mail site': 'email_login_link',
    '2fa website': 'email_login_link',
    'rockstar mail login link': 'email_login_link',
    'mail log in here': 'email_login_link',
    'mail domain': 'email_login_link',
    # Security email
    'security email': 'security_email',
    'security mail': 'security_email',
    'reserve email': 'security_email',
    '2fa mail': 'security_email',
    '2fa email': 'security_email',
    'rockstar email': 'security_email',
    'rockstar mail': 'security_email',
    # Security email password
    'security email password': 'security_email_password',
    'security mail password': 'security_email_password',
    'rockstar email password': 'security_email_password',
    'rockstar mail password': 'security_email_password',
}

# Separators between label and value
_ARROW_RE = re.compile(r'^(.+?)\s*-+>\s*(.*)$')
_COLON_RE = re.compile(r'^(.+?):\s*(.*)$')

# Space-separated labels (no colon/arrow) — order matters, longest first
_SPACE_LABEL_RE = re.compile(
    r'^(mail\s+password|psn\s+password|epic\s+password|epic\s+pw|mail\s+pw'
    r'|epic\s+p|mail\s+p)\s+(.+)$',
    re.IGNORECASE,
)

# Section headers that introduce a login:password pair on the next line.
# Includes verbose forms ("Epic Games Details:") and bare platform keywords
# ("epic", "riot", "mail") that sellers use as section dividers.
_SECTION_HEADER_RE = re.compile(
    r'^(Epic\s+Games\s+Details|E-?mail\s+(?:Details|Sign\s*in\s+Details)'
    r'|Riot\s+Sign\s*in\s+Details|Rainbow\s+Sign\s*in\s+Details'
    r'|Ubisoft\s+Sign\s+Details|Account\s+(?:Login\s+)?Details'
    r'|account\s+info|mail\s+info'
    r'|epic|riot|ubi|ubisoft|steam|mail)\s*[-:>]*\s*$',
    re.IGNORECASE,
)

# Section header labels that can appear inline with "Label: login: password"
_INLINE_SECTION_LABELS = {'account info', 'mail info', 'epic info'}

# Maps section header type to which fields the next login:pass pair fills
_SECTION_FIELD_MAP: dict[str, tuple[str, str]] = {
    'epic': ('login', 'password'),
    'riot': ('login', 'password'),
    'rainbow': ('login', 'password'),
    'ubisoft': ('login', 'password'),
    'ubi': ('login', 'password'),
    'steam': ('login', 'password'),
    'account': ('login', 'password'),
    'e-mail': ('email', 'email_password'),
    'email': ('email', 'email_password'),
    'mail': ('email', 'email_password'),
}

# Patterns to detect URLs (for email_login_link)
_URL_PATTERN = re.compile(r'https?://|\.com/|\.ltd/|\.ru/')

# "xxx@yyy.com is security mail/maik" pattern
_IS_SECURITY_RE = re.compile(
    r'([\w.+-]+@[\w.-]+\.\w+)\s+is\s+security\s+(?:mail|maik)',
    re.IGNORECASE,
)

# Bare domain: "rambler.ru", "mail.rambler.ru", "firstmail.ltd"
_BARE_DOMAIN_RE = re.compile(r'^(?:mail\.)?[\w.-]+\.(?:ru|com|ltd|net|org|io)$', re.IGNORECASE)

# "come chat" / "cometochat" / "comechatformailaccess" placeholder values from sellers
_BOGUS_VALUE_RE = re.compile(
    r'^come\s*(?:to\s*)?(?:ch|ca|ac|cc)'   # comechat, cometochat, come acht, come cchat
    r'|^come\s*(?:to\s*)?char'             # cometochar
    r'|^come$',                             # standalone "come"
    re.IGNORECASE,
)

# Email at start of line followed by extra content: "email@x.com  Mail password xxx"
_EMAIL_PREFIX_RE = re.compile(r'^([\w.+-]+@[\w.-]+\.\w+)\s{2,}(.+)$')

# Lines to skip entirely
_SKIP_PREFIXES = (
    'important', 'you need to', 'do not', "don't",
    'your epic games password',
    'thanks for purchase', 'your account is sending',
    'if ps5 password', 'if ps4 password',
    'you can login in',
    'no pass', 'not a 24/7', 'please wait',
    # Disclaimers / seller messages
    'we resolve',
    # Template / format description lines
    'format',
    # Instruction text (OSRS TOTP, setup guides, etc.)
    'how to', 'go to', 'paste the', 'it will generate',
    'use the', 'want to change', 'you can log',
    'all changes', 'only use', 'change email',
    'your purchase', 'login instructions', 'secret key',
    'webmail login', 'date of birth',
)

# Regex to strip leading emojis/symbols before skip-prefix check
_LEADING_SYMBOLS_RE = re.compile(r'^[\W_]+', re.UNICODE)


def _should_skip_line(lower: str) -> bool:
    """Check if a line should be skipped (instructions, disclaimers, etc).

    Strips leading emojis/symbols before checking prefixes so that
    lines like "⚠️ Important: ..." are correctly skipped.
    """
    if any(lower.startswith(p) for p in _SKIP_PREFIXES):
        return True
    # Strip leading emojis/symbols and re-check
    stripped = _LEADING_SYMBOLS_RE.sub('', lower).strip()
    if stripped and any(stripped.startswith(p) for p in _SKIP_PREFIXES):
        return True
    return False


def parse_credentials_text(text: str) -> ParsedCredentials:
    """Parse a free-text credential string into structured fields.

    Tries labeled formats first (Login:, ->, mail:), then falls back
    to positional parsing (colon-separated, tab-separated, newline pairs).
    """
    if not text or not text.strip():
        return ParsedCredentials()

    # Deduplicate consecutive identical lines
    # Handles "email\tpass\nemail\tpass" duplicate patterns
    raw_lines = text.split('\n')
    deduped: list[str] = []
    for raw_line in raw_lines:
        if not deduped or raw_line != deduped[-1]:
            deduped.append(raw_line)
    text = '\n'.join(deduped)

    result = ParsedCredentials()

    # Try labeled parsing first
    labeled = _parse_labeled(text, result)
    if labeled:
        _post_process(result)
        # If login was cleared as bogus (instruction text), fall back to positional
        if not result.login:
            result = ParsedCredentials()
            _parse_positional(text, result)
            _post_process(result)
        return result

    # Fallback to positional parsing
    _parse_positional(text, result)
    _post_process(result)
    return result


def _parse_labeled(text: str, result: ParsedCredentials) -> bool:
    """Try to parse text as labeled key-value lines.

    Returns True if at least one labeled field was found.
    Also captures the first unlabeled line as a potential login.
    """
    found_any = False
    first_unlabeled: str | None = None
    second_unlabeled: str | None = None
    lines = text.split('\n')
    i = 0
    skip_next_line = False

    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if not line:
            continue

        # Skip template description line that follows a "Format:" header
        if skip_next_line:
            skip_next_line = False
            continue

        lower = line.lower()
        if _should_skip_line(lower):
            # "Format:" headers are followed by template descriptions — skip those too
            stripped_lower = _LEADING_SYMBOLS_RE.sub('', lower).strip()
            if lower.startswith('format') or stripped_lower.startswith('format'):
                skip_next_line = True
            continue

        # Check for "xxx@yyy.com is security mail/maik"
        sec_match = _IS_SECURITY_RE.search(line)
        if sec_match:
            if not result.security_email:
                result.security_email = sec_match.group(1)
            found_any = True
            # Check if there's credential content before the security mention
            before = line[:sec_match.start()].strip()
            if before and '@' in before and ':' in before:
                if first_unlabeled is None:
                    first_unlabeled = before
            continue

        # Check for section header (Epic Games Details:, account info:, etc.)
        header_match = _SECTION_HEADER_RE.match(line)
        if header_match:
            # Next non-empty line should be login:password or login : password
            while i < len(lines):
                next_line = lines[i].strip()
                i += 1
                if next_line:
                    _parse_section_pair(header_match.group(1), next_line, result)
                    found_any = True
                    break
            continue

        # Try arrow format: "Key -> Value" or "Key --> Value"
        match = _ARROW_RE.match(line)
        if match:
            # Check for multiple arrow pairs on the same line
            arrow_pairs = _split_arrow_pairs(line)
            if arrow_pairs:
                for a_label, a_value in arrow_pairs:
                    if _assign_labeled(a_label, a_value, result):
                        found_any = True
                continue

            label = match.group(1).strip()
            value = match.group(2).strip()
            # If value is empty, check next line
            if not value and i < len(lines):
                next_line = lines[i].strip()
                if next_line and not _ARROW_RE.match(next_line) and not _COLON_RE.match(next_line):
                    value = next_line
                    i += 1
            if _assign_labeled(label, value, result):
                found_any = True
                continue
            # Arrow label not recognized — the "->" may be inside a value
            # e.g. "Password: p2|KDu->Vf{ks@C" — fall through to colon parsing

        # Try colon format: "Key: Value"
        match = _COLON_RE.match(line)
        if match:
            label = match.group(1).strip()
            value = match.group(2).strip()

            # Skip if label looks like an email (email:password pattern)
            if '@' in label:
                if first_unlabeled is None:
                    first_unlabeled = line
                continue

            # Check for multiple colon-labeled pairs on one line
            # e.g., "steam ID: x steam password: y" or "email: a@b.c email password: z"
            colon_pairs = _split_colon_pairs(line)
            if colon_pairs and len(colon_pairs) >= 2:
                for c_label, c_value in colon_pairs:
                    if _assign_labeled(c_label, c_value, result):
                        found_any = True
                # Multi-pair line fully handled — skip single-colon fallback
                continue

            # Inline section header: "Account info: Username: Password"
            # The label is a section header keyword and value contains login:pass
            if label.lower().strip() in _INLINE_SECTION_LABELS and ':' in value:
                _parse_section_pair(label, value, result)
                found_any = True
                continue

            if _assign_labeled(label, value, result):
                found_any = True
                # If suffix matching was used for a password field,
                # the prefix portion is likely the login.
                # e.g., "DriftStar453 Password: xxx" → login=DriftStar453
                if not result.login:
                    _extract_login_from_password_label(label, result)
                continue

            # Label with empty value — check if it's a recognized label
            # whose value is on the next line (e.g., "E-mail sign in link:\n\tURL")
            if not value:
                normalized = label.lower().strip()
                field_name = (
                    _LABEL_MAP.get(normalized)
                    or _suffix_match_label(normalized)
                )
                if field_name and i < len(lines):
                    next_line = lines[i].strip()
                    if next_line and not getattr(result, field_name):
                        setattr(result, field_name, next_line)
                        found_any = True
                        i += 1
                        continue

            # Check if this is a section-like header with empty or label-like value
            # e.g., "Mail: Mail password:" or "epic:" followed by email on next line
            if not value or value.lower().rstrip(':') in _LABEL_MAP:
                # Look for login:pass pair on next line
                if i < len(lines):
                    next_line = lines[i].strip()
                    if next_line and ':' in next_line:
                        _parse_section_pair(label, next_line, result)
                        found_any = True
                        i += 1
                        continue

            # Unrecognized colon line — treat as unlabeled
            if first_unlabeled is None:
                first_unlabeled = line
            continue

        # Try space-separated label: "Mail password xxx" (no colon/arrow)
        space_match = _SPACE_LABEL_RE.match(line)
        if space_match:
            label = space_match.group(1).strip()
            value = space_match.group(2).strip()
            if _assign_labeled(label, value, result):
                found_any = True
            continue

        # Bare label without value — value is on the next line
        # e.g., "Mail password\n\t0k1LlNumI7W" or "Mail pass\nvalue"
        bare_normalized = line.lower().strip()
        # Only direct match — suffix matching is too aggressive for bare labels
        # (e.g., "Mail login" would suffix-match "login" which is wrong)
        bare_field = _LABEL_MAP.get(bare_normalized)
        if bare_field and i < len(lines):
            next_line = lines[i].strip()
            if next_line and not getattr(result, bare_field):
                # Don't use instruction/disclaimer text as value
                if not _should_skip_line(next_line.lower()):
                    setattr(result, bare_field, next_line)
                    found_any = True
                    i += 1
                    continue

        # Bare URL line — could be email_login_link
        if _URL_PATTERN.search(line) and not result.email_login_link:
            result.email_login_link = line
            found_any = True
            continue

        # Bare domain: "rambler.ru", "mail.rambler.ru"
        if _BARE_DOMAIN_RE.match(line) and not result.email_login_link:
            result.email_login_link = line
            found_any = True
            continue

        # "email@x.com  Mail password xxx" — email + space-separated label on same line
        email_prefix_match = _EMAIL_PREFIX_RE.match(line)
        if email_prefix_match:
            email_part = email_prefix_match.group(1)
            rest_part = email_prefix_match.group(2).strip()
            if first_unlabeled is None:
                first_unlabeled = email_part
            # Try to parse the rest as a space-separated label
            space_match = _SPACE_LABEL_RE.match(rest_part)
            if space_match:
                _assign_labeled(space_match.group(1).strip(), space_match.group(2).strip(), result)
                found_any = True
            continue

        # Track first/second unlabeled line (potential login/password)
        if first_unlabeled is None:
            first_unlabeled = line
        elif second_unlabeled is None:
            second_unlabeled = line

    # If we found labeled fields but login is empty, use first unlabeled line
    if found_any and not result.login and first_unlabeled:
        if '\t' in first_unlabeled:
            # Tab in unlabeled line — split as login\tpassword
            parts = first_unlabeled.split('\t')
            result.login = parts[0].strip()
            if len(parts) >= 2 and parts[1].strip() and not result.password:
                result.password = parts[1].strip()
        elif ':' in first_unlabeled:
            # Colon-separated credential line (user:pass or email:pass)
            _parse_colon_line(first_unlabeled, result)
        else:
            _parse_single_token(first_unlabeled, result)
        # first_unlabeled consumed for login
        first_unlabeled = None

    # If password still empty, use first unlabeled (when login was from labels/section)
    # or second unlabeled line — but never use instruction/disclaimer text
    if found_any and not result.password:
        candidate = first_unlabeled or second_unlabeled
        if candidate and not _should_skip_line(candidate.lower()):
            result.password = candidate

    return found_any


# Regex to find all "Key ->" boundaries in a single line
# Label is one or more words (letters, spaces, hyphens) before the arrow
_MULTI_ARROW_LABEL_RE = re.compile(
    r'(?:^|\s)((?:[A-Za-z][\w-]*\s+)*[A-Za-z][\w-]*)\s*-+>',
)


def _split_arrow_pairs(line: str) -> list[tuple[str, str]] | None:
    """Split a line with multiple 'Key -> Value' pairs.

    Returns list of (label, value) tuples, or None if only one arrow.
    Example: "Device ID -> user@x.com Device Password -> pass123"
    → [("Device ID", "user@x.com"), ("Device Password", "pass123")]
    """
    splits = list(_MULTI_ARROW_LABEL_RE.finditer(line))
    if len(splits) < 2:
        return None

    pairs: list[tuple[str, str]] = []
    for idx, m in enumerate(splits):
        label = m.group(1).strip()
        # Value starts after "Label ->" (find arrow end)
        arrow_end = line.index('->', m.end() - 2) + 2
        while arrow_end < len(line) and line[arrow_end] in ' >':
            arrow_end += 1
        # Value ends where the next label starts (at the match start of next pair)
        if idx + 1 < len(splits):
            next_match = splits[idx + 1]
            # The next label might start mid-word, so use the full match start
            value_end = next_match.start()
            # If the match started with \s, the label begins after that space
            if line[next_match.start()] == ' ':
                value_end = next_match.start()
        else:
            value_end = len(line)
        value = line[arrow_end:value_end].strip()
        pairs.append((label, value))
    return pairs


def _split_colon_pairs(line: str) -> list[tuple[str, str]] | None:
    """Split a line with multiple 'Label: Value' pairs.

    Scans for known labels (from _LABEL_MAP or suffix-matchable) followed
    by ':' to identify pair boundaries.
    Example: "steam ID: user123 steam password: pass456"
    → [("steam ID", "user123"), ("steam password", "pass456")]
    """
    # Find all colon positions
    colon_positions = [i for i, c in enumerate(line) if c == ':']
    if len(colon_positions) < 2:
        return None

    # For each colon, check if the text before it (up to prev value end) is a known label
    pair_starts: list[tuple[int, int, str]] = []  # (label_start, colon_pos, label)
    for cp in colon_positions:
        # Extract candidate label: go backwards from colon to find label start
        # Label can be multi-word, try progressively longer prefixes
        before = line[:cp].rstrip()
        if not before:
            continue
        # Try to find the longest DIRECT-match label ending at this colon.
        # Only use _LABEL_MAP direct matches (no suffix matching) to avoid
        # picking up value words as part of the label in multi-pair lines.
        best_label: str | None = None
        best_start: int = -1
        words = before.split()
        for w_start in range(len(words)):
            candidate = ' '.join(words[w_start:])
            normalized = candidate.lower()
            if '@' in candidate:
                continue
            if _LABEL_MAP.get(normalized):
                # Calculate start position in original string
                label_start = before.index(candidate, max(0, len(before) - len(candidate) - 1))
                if best_label is None or len(candidate) > len(best_label):
                    best_label = candidate
                    best_start = label_start
        if best_label is not None:
            pair_starts.append((best_start, cp, best_label))

    if len(pair_starts) < 2:
        return None

    pairs: list[tuple[str, str]] = []
    for idx, (label_start, cp, label) in enumerate(pair_starts):
        value_start = cp + 1
        # Skip whitespace after colon
        while value_start < len(line) and line[value_start] == ' ':
            value_start += 1
        # Value ends at start of next label
        if idx + 1 < len(pair_starts):
            value_end = pair_starts[idx + 1][0]
        else:
            value_end = len(line)
        value = line[value_start:value_end].strip()
        pairs.append((label, value))
    return pairs


def _parse_section_pair(
    header: str, pair_line: str, result: ParsedCredentials,
) -> None:
    """Parse a login:password pair from a section header context.

    The header tells us which fields to fill (login/password vs email/email_password).
    """
    header_lower = header.lower().strip()

    # Determine target fields from section type
    login_field = 'login'
    pass_field = 'password'
    for prefix, (lf, pf) in _SECTION_FIELD_MAP.items():
        if prefix in header_lower:
            login_field = lf
            pass_field = pf
            break

    # Parse the pair line: "email : pass" or "email:pass"
    # Skip garbage lines (just punctuation, whitespace, or empty)
    cleaned = pair_line.strip(':').strip()
    if not cleaned:
        return

    match = _COLON_RE.match(pair_line)
    if match:
        login_val = match.group(1).strip()
        pass_val = match.group(2).strip()

        # If the pair_line is itself a labeled line (e.g. "Login: user123" inside a
        # STEAM section), use the labeled value rather than treating "Login" as
        # the username.  This handles multi-line sections like:
        #   STEAM:↵Login: user123↵Password: pass  (remaining lines parsed by main loop)
        if login_val and '@' not in login_val:
            normalized = login_val.lower()
            if _LABEL_MAP.get(normalized) or _suffix_match_label(normalized):
                _assign_labeled(login_val, pass_val, result)
                return

        if login_val and not getattr(result, login_field):
            setattr(result, login_field, login_val)
        if pass_val and not getattr(result, pass_field):
            setattr(result, pass_field, pass_val)
    else:
        # No colon — treat entire line as login value only
        if pair_line and not getattr(result, login_field):
            setattr(result, login_field, pair_line)


def _assign_labeled(label: str, value: str, result: ParsedCredentials) -> bool:
    """Try to assign a labeled value to the result. Returns True if matched."""
    if not value:
        return False

    # Strip leading "- " from value (handles ":- value" separator format)
    value = value.lstrip('- ').strip() if value.startswith('-') else value
    if not value:
        return False

    # Reject values that are themselves known label names (template text)
    # e.g., "Mail password" in "Mail:Account password:Mail password" template
    if value.lower().rstrip(':') in _LABEL_MAP:
        return False

    normalized = label.lower().strip()
    field_name = _LABEL_MAP.get(normalized)

    # Suffix matching: strip prefix words until a known label is found.
    # Handles "Ubisoft Account Password -> x" → suffix "account password" → password
    # and "Markt123123 E-mail -> x" → suffix "e-mail" → email
    if not field_name:
        field_name = _suffix_match_label(normalized)

    if field_name:
        # Value may contain "email:password" when label maps to login/email.
        # e.g. "epic : user@x.com : pass"  → login=user@x.com, epic_pass (→ password via post_process)
        # e.g. "mail : user@x.com : pass"  → email=user@x.com, email_password=pass
        if field_name in ('login', 'email') and '@' in value and ':' in value:
            parts = value.split(':', 1)
            if '@' in parts[0]:
                target = 'login' if field_name == 'login' else 'email'
                if not getattr(result, target):
                    setattr(result, target, parts[0].strip())
                if parts[1].strip() and not result.email_password:
                    result.email_password = parts[1].strip()
                return True

        # Only set if not already filled (first match wins)
        if not getattr(result, field_name):
            setattr(result, field_name, value)
        return True

    return False


def _suffix_match_label(normalized: str) -> str | None:
    """Try to match a label by stripping prefix words.

    Returns field_name if a known suffix is found, None otherwise.
    """
    words = normalized.split()
    for start in range(1, len(words)):
        suffix = ' '.join(words[start:])
        field_name = _LABEL_MAP.get(suffix)
        if field_name:
            return field_name
    return None


_LOGIN_PREFIX_REJECT = {
    'epic', 'games', 'mail', 'email', 'e-mail', 'psn', 'xbox',
    'riot', 'steam', 'rockstar', 'ubisoft', 'account', 'device',
    'supercell', 'roblox', '&', 'and', 'password', 'the',
}


def _extract_login_from_password_label(label: str, result: ParsedCredentials) -> None:
    """Extract login from label prefix when suffix matched a password field.

    Example: label="DriftStar453 Password" → suffix "password" matched,
    prefix "DriftStar453" is the login.
    Also handles ":LAGRANDE_STOCK1 pass" → "LAGRANDE_STOCK1".
    """
    normalized = label.lower().strip()
    if normalized in _LABEL_MAP:
        # Direct match, no prefix to extract
        return

    words = normalized.split()
    original_words = label.strip().split()
    for start in range(1, len(words)):
        suffix = ' '.join(words[start:])
        if _LABEL_MAP.get(suffix) == 'password':
            prefix = ' '.join(original_words[:start]).strip().lstrip(':').strip()
            # Clean trailing punctuation (commas, semicolons) and whitespace
            prefix = prefix.rstrip(',:;').strip()
            if not prefix:
                return
            # Reject if prefix contains common credential label words
            prefix_words = {w.lower() for w in prefix.split()}
            if prefix_words & _LOGIN_PREFIX_REJECT:
                return
            result.login = prefix
            return


def _parse_positional(text: str, result: ParsedCredentials) -> None:
    """Fallback: parse by position using delimiters.

    Handles:
      - "email@x.com:password" (colon)
      - "email@x.com:pass.:email@x.com:pass2\\nsecurity@x.com..." (multi-colon)
      - "email@x.com\\tpassword" (tab)
      - "email@x.com\\tpass\\temail\\temail_pass\\t\\t\\twebmail" (multi-tab)
      - "email@x.com\\npassword" (newline)
    """
    stripped = text.strip()

    # Tab-separated: split by tabs (but not if mixed with labeled lines)
    if '\t' in stripped:
        # Check if it's pure tab-separated or mixed with labeled content
        non_tab_lines = [
            l.strip() for l in stripped.replace('\t', '\n').split('\n')
            if l.strip()
        ]
        has_labels = any(
            (_COLON_RE.match(l) and '@' not in l.split(':')[0])
            or _SPACE_LABEL_RE.match(l)
            or l.lower().strip() in _LABEL_MAP
            for l in non_tab_lines
        )
        if has_labels:
            # Mixed: treat tabs as newlines and parse as labeled
            normalized = stripped.replace('\t', '\n')
            if _parse_labeled(normalized, result):
                return
        _parse_tab_separated(stripped, result)
        return

    lines = [l.strip() for l in stripped.split('\n') if l.strip()]

    # Single line with colons — email:password or multi-colon
    if len(lines) == 1 and ':' in lines[0]:
        _parse_colon_line(lines[0], result)
        return

    # Multi-line: first line has email:pass format
    if lines and ':' in lines[0] and '@' in lines[0]:
        _parse_colon_line(lines[0], result)
        # Remaining lines may have security email info or URLs
        for line in lines[1:]:
            lower = line.lower()
            # "xxx@yyy.com is security mail/maik"
            sec_match = _IS_SECURITY_RE.search(line)
            if sec_match:
                if not result.security_email:
                    result.security_email = sec_match.group(1)
                continue
            if 'security' in lower or 'reserve' in lower or '2fa' in lower:
                # Try labeled: "security mail: xxx"
                match = _COLON_RE.match(line)
                if match:
                    _assign_labeled(match.group(1).strip(), match.group(2).strip(), result)
                    continue
                # Try to extract email from text: "security mail:\nxxx@yyy.com"
                email = _extract_email_from_text(line)
                if email and not result.security_email:
                    result.security_email = email
                    continue
            elif ':' in line and '@' in line:
                # Another email:pass pair — could be security email
                parts = line.split(':', 1)
                email_part = parts[0].strip()
                pass_part = parts[1].strip() if len(parts) > 1 else ''
                if '@' in email_part:
                    if not result.security_email:
                        result.security_email = email_part
                    if pass_part and not result.security_email_password:
                        result.security_email_password = pass_part
                continue
            elif _URL_PATTERN.search(line) and not result.email_login_link:
                result.email_login_link = line
            # Plain domain like "rambler.ru" — could be email login link
            elif re.match(r'^[\w.-]+\.\w{2,}$', line) and not result.email_login_link:
                result.email_login_link = line
        return

    # Newline pairs: first line = login, second = password
    if len(lines) >= 2:
        _parse_newline_pairs(lines, result)
        return

    # Single line, no delimiter
    if len(lines) == 1:
        _parse_single_token(lines[0], result)


# 2+ consecutive spaces — "username    password" separator
_MULTI_SPACE_RE = re.compile(r'^(\S+)\s{2,}(\S+)$')

# email@domain.com single_word — single space between email and non-email token
_EMAIL_SINGLE_SPACE_RE = re.compile(
    r'^([\w.+-]+@[\w.-]+\.\w+)\s+(\S+)$',
)

# "login XXX password YYY" or "login-XXX password-YYY" inline format
_INLINE_LOGIN_PASS_RE = re.compile(
    r'^login[\s:-]+(\S+)\s+password[\s:-]+(\S+)$',
    re.IGNORECASE,
)


def _parse_single_token(token: str, result: ParsedCredentials) -> None:
    """Parse a single token that has no colon/tab/arrow delimiter.

    If it contains 2+ consecutive spaces, split as login + password.
    If it's email + single space + non-email word, split as login + password.
    Otherwise treat the whole token as login.
    """
    # "login XXX password YYY" or "login-XXX password-YYY"
    inline_match = _INLINE_LOGIN_PASS_RE.match(token)
    if inline_match:
        result.login = inline_match.group(1)
        if not result.password:
            result.password = inline_match.group(2)
        return

    match = _MULTI_SPACE_RE.match(token)
    if match:
        result.login = match.group(1)
        if not result.password:
            result.password = match.group(2)
        return

    # email@domain.com password — single space, non-label word
    email_match = _EMAIL_SINGLE_SPACE_RE.match(token)
    if email_match:
        candidate = email_match.group(2)
        # Only split if the second part is NOT a known label keyword
        if candidate.lower() not in _LABEL_MAP:
            result.login = email_match.group(1)
            if not result.password:
                result.password = candidate
            return

    result.login = token


def _parse_colon_line(line: str, result: ParsedCredentials) -> None:
    """Parse colon-separated credential line.

    Common patterns:
      - "email@x.com:password"
      - "email@x.com:pass.:email@x.com:pass2 reserve email: ..."
    """
    # Check for "reserve email:" or similar at the end
    reserve_match = re.search(
        r'\s+(?:reserve|security|2fa)\s+(?:email|mail)\s*:\s*(.+)',
        line, re.IGNORECASE,
    )
    if reserve_match:
        rest = reserve_match.group(1).strip()
        # rest might be "email@x.com|password url"
        parts = re.split(r'[|\s]+', rest)
        if parts:
            result.security_email = parts[0]
        if len(parts) >= 2:
            result.security_email_password = parts[1]
        if len(parts) >= 3 and _URL_PATTERN.search(parts[2]):
            result.email_login_link = parts[2]
        # Trim the reserve part from the main line
        line = line[:reserve_match.start()]

    # Check for "is security mail/maik" at the end
    sec_match = _IS_SECURITY_RE.search(line)
    if sec_match:
        if not result.security_email:
            result.security_email = sec_match.group(1)
        line = line[:sec_match.start()].strip()

    parts = line.split(':')

    if len(parts) >= 2:
        if not result.login:
            result.login = parts[0].strip()
        if not result.password:
            result.password = parts[1].strip()

    if len(parts) >= 4:
        if not result.email:
            result.email = parts[2].strip()
        if not result.email_password:
            result.email_password = parts[3].strip()


def _parse_tab_separated(text: str, result: ParsedCredentials) -> None:
    """Parse tab-separated credentials.

    Common pattern: login\\tpassword\\temail\\temail_pass\\t\\t\\twebmail_url
    Consecutive tabs (empty parts) are skipped to avoid index shifting.
    """
    # Filter out empty parts from consecutive tabs
    parts = [p for p in text.split('\t') if p.strip()]
    fields = ['login', 'password', 'email', 'email_password',
              'security_email', 'security_email_password', 'email_login_link']

    for i, field_name in enumerate(fields):
        if i < len(parts) and parts[i].strip():
            setattr(result, field_name, parts[i].strip())


def _parse_newline_pairs(lines: list[str], result: ParsedCredentials) -> None:
    """Parse newline-separated credential pairs.

    First non-label line = login, next = password, etc.
    Also checks for labeled lines mixed in.
    """
    unlabeled: list[str] = []

    for line in lines:
        lower = line.lower()

        # Skip instruction/note lines
        if _should_skip_line(lower):
            continue

        # Check for "xxx@yyy.com is security mail/maik"
        sec_match = _IS_SECURITY_RE.search(line)
        if sec_match:
            if not result.security_email:
                result.security_email = sec_match.group(1)
            continue

        # Try space-separated label first: "Mail password xxx"
        space_match = _SPACE_LABEL_RE.match(line)
        if space_match:
            label = space_match.group(1).strip()
            value = space_match.group(2).strip()
            if _assign_labeled(label, value, result):
                continue

        # Check if it's a labeled line
        match = _COLON_RE.match(line)
        if match:
            label = match.group(1).strip()
            value = match.group(2).strip()
            if '@' not in label and _assign_labeled(label, value, result):
                continue

        # Check for URL
        if _URL_PATTERN.search(line) and not result.email_login_link:
            result.email_login_link = line
            continue

        # Security/reserve email mention
        if ('security' in lower or 'reserve' in lower or '2fa' in lower) and '@' in line:
            email = _extract_email_from_text(line)
            if email and not result.security_email:
                result.security_email = email
                continue

        # Plain domain like "rambler.ru" — could be email login link
        if re.match(r'^[\w.-]+\.\w{2,}$', line) and not result.email_login_link:
            result.email_login_link = line
            continue

        unlabeled.append(line)

    # Map unlabeled lines positionally
    positional_fields = ['login', 'password']
    for i, field_name in enumerate(positional_fields):
        if i < len(unlabeled) and not getattr(result, field_name):
            setattr(result, field_name, unlabeled[i])


_ARTIFACT_PREFIXES = (': ', '-> ', ':- ')


def _strip_field_artifacts(result: ParsedCredentials) -> None:
    """Strip leading separator artifacts from credential values."""
    for field_name in ('login', 'password', 'email', 'email_password',
                       'email_login_link', 'security_email', 'security_email_password'):
        val = getattr(result, field_name)
        if not val:
            continue
        for prefix in _ARTIFACT_PREFIXES:
            if val.startswith(prefix):
                val = val[len(prefix):].strip()
                break
        if val != getattr(result, field_name):
            setattr(result, field_name, val)


def _clear_bogus_values(result: ParsedCredentials) -> None:
    """Clear credential fields that contain instruction/placeholder text."""
    for field_name in ('login', 'password', 'email', 'email_password',
                       'email_login_link', 'security_email', 'security_email_password'):
        val = getattr(result, field_name)
        if not val:
            continue
        lower = val.lower()
        # Instruction text as value (e.g. "You need to reset the PSN password")
        if _should_skip_line(lower):
            setattr(result, field_name, '')
            continue
        # "come chat" placeholder variants
        if _BOGUS_VALUE_RE.match(val):
            setattr(result, field_name, '')
            continue
        # Value is a known label name → template text (e.g. "Mail password", "Account")
        if field_name in ('password', 'email', 'email_password') and lower.rstrip(':') in _LABEL_MAP:
            setattr(result, field_name, '')
            continue
        # Login: reject if it's a bare platform/label keyword (parser artefact)
        if field_name == 'login' and lower.rstrip(':') in _LABEL_MAP and '@' not in val:
            setattr(result, field_name, '')
            continue
        # Login: reject if it looks like a sentence (4+ words, not an email)
        if field_name == 'login' and '@' not in val and len(val.split()) >= 4:
            setattr(result, field_name, '')
            continue
        # Email: reject if doesn't contain @ and has template keywords
        if field_name == 'email' and '@' not in val:
            if 'password' in lower:
                setattr(result, field_name, '')


def _post_process(result: ParsedCredentials) -> None:
    """Fill in gaps and sanitize using available data.

    1. Strip leading separator artifacts (": ", "-> ")
    2. Clear bogus/instruction values
    3. Fill gaps: login ↔ email, email_password → password
    """
    _strip_field_artifacts(result)
    _clear_bogus_values(result)

    if not result.login and result.email:
        result.login = result.email
    if not result.email and result.login and '@' in result.login:
        result.email = result.login
    # When account login IS the email, email_password is the account password
    if not result.password and result.email_password and result.login:
        if result.login == result.email:
            result.password = result.email_password


def _extract_email_from_text(text: str) -> str:
    """Extract first email address from a text string."""
    match = re.search(r'[\w.+-]+@[\w.-]+\.\w+', text)
    return match.group(0) if match else ''
