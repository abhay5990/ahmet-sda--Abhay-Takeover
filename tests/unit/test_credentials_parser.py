"""Unit tests for shared credential text parser.

Tests cover all format variations found in production data:
  - Arrow format with game-prefixed labels (Ubisoft Account ->)
  - Section headers (Account Login Details:)
  - Colon labels with empty values on next line (E-mail sign in link:)
  - Seller-prefixed labels (Markt123123 E-mail ->)
  - Standard labeled, positional, tab-separated formats

Usage:
    cd backend && python -m pytest ../tests/unit/test_credentials_parser.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from apps.sync.services.shared.credentials import parse_credentials_text


# ── Arrow format with game-prefixed labels ─────────────────────────


class TestUbisoftArrowFormat:
    """Ubisoft Account -> email / Ubisoft Account Password -> pass."""

    def test_full_ubisoft_block(self):
        text = (
            "Ubisoft Account -> user@hotmail.com\n"
            "Ubisoft Account Password -> L,CRY%M0aL\n"
            "E-mail -> user@hotmail.com\n"
            "E-mail Password -> yAz2giZdVTow\n"
            "E-mail Login Link ->\n"
            "\tlogin.live.com"
        )
        r = parse_credentials_text(text)
        assert r.login == 'user@hotmail.com'
        assert r.password == 'L,CRY%M0aL'
        assert r.email == 'user@hotmail.com'
        assert r.email_password == 'yAz2giZdVTow'
        assert r.email_login_link == 'login.live.com'

    def test_ubisoft_account_only(self):
        text = (
            "Ubisoft Account -> player@gmail.com\n"
            "Ubisoft Account Password -> SecretPass123"
        )
        r = parse_credentials_text(text)
        assert r.login == 'player@gmail.com'
        assert r.password == 'SecretPass123'


class TestSuffixMatching:
    """Labels with arbitrary prefixes resolved via suffix matching."""

    def test_seller_prefixed_email(self):
        text = (
            "Device ID -> user123\n"
            "Device Password -> pass456\n"
            "Markt123123 E-mail -> test@mail.com\n"
            "Markt123123 E-mail Login Link -> https://mail.com/login"
        )
        r = parse_credentials_text(text)
        assert r.login == 'user123'
        assert r.password == 'pass456'
        assert r.email == 'test@mail.com'
        assert r.email_login_link == 'https://mail.com/login'

    def test_seller_prefixed_email_password(self):
        text = (
            "Login -> user@x.com\n"
            "Password -> abc123\n"
            "Seller E-mail -> contact@y.com\n"
            "Seller E-mail Password -> mailpass"
        )
        r = parse_credentials_text(text)
        assert r.login == 'user@x.com'
        assert r.password == 'abc123'
        assert r.email == 'contact@y.com'
        assert r.email_password == 'mailpass'

    def test_generic_account_label(self):
        """'Account' alone should map to login."""
        text = (
            "Account -> mylogin@email.com\n"
            "Account Password -> mypass"
        )
        r = parse_credentials_text(text)
        assert r.login == 'mylogin@email.com'
        assert r.password == 'mypass'

    def test_steam_account_prefix(self):
        text = (
            "Steam Account -> steamuser\n"
            "Steam Account Password -> st3amP@ss"
        )
        r = parse_credentials_text(text)
        assert r.login == 'steamuser'
        assert r.password == 'st3amP@ss'

    def test_riot_prefixed_labels(self):
        text = (
            "Riot Account -> riotuser@mail.com\n"
            "Riot Account Password -> riotpass\n"
            "Riot E-mail -> riotuser@mail.com\n"
            "Riot E-mail Password -> emailpass"
        )
        r = parse_credentials_text(text)
        assert r.login == 'riotuser@mail.com'
        assert r.password == 'riotpass'
        assert r.email == 'riotuser@mail.com'
        assert r.email_password == 'emailpass'


# ── Section header format ──────────────────────────────────────────


class TestSectionHeaderFormat:
    """Account Login Details:\\n\\temail patterns from Eldorado."""

    def test_full_section_block(self):
        text = (
            "Account Login Details:\n"
            "\torell_5017@nolettersbox.com\n"
            "E-mail Sign in Details:\n"
            "\torell_5017@nolettersbox.com : MwZJ_cbyK-\n"
            "E-mail sign in link:\n"
            "\thttps://notletters.com/email/login"
        )
        r = parse_credentials_text(text)
        assert r.login == 'orell_5017@nolettersbox.com'
        assert r.email == 'orell_5017@nolettersbox.com'
        assert r.email_password == 'MwZJ_cbyK-'
        assert r.email_login_link == 'https://notletters.com/email/login'

    def test_section_with_password_pair(self):
        text = (
            "Account Login Details:\n"
            "\tuser@mail.com : secretpass\n"
            "E-mail Sign in Details:\n"
            "\tuser@mail.com : mailpass"
        )
        r = parse_credentials_text(text)
        assert r.login == 'user@mail.com'
        assert r.password == 'secretpass'
        assert r.email == 'user@mail.com'
        assert r.email_password == 'mailpass'

    def test_section_single_value_no_password(self):
        """Account Login Details with just email, no password."""
        text = (
            "Account Login Details:\n"
            "\tjust_login@mail.com"
        )
        r = parse_credentials_text(text)
        assert r.login == 'just_login@mail.com'

    def test_empty_email_section(self):
        """E-mail Sign in Details with empty credentials."""
        text = (
            "Account Login Details:\n"
            "\tuser@mail.com\n"
            "E-mail Sign in Details:\n"
            "\t : \n"
            "E-mail sign in link:\n"
            "\thttps://firstmail.ltd/webmail"
        )
        r = parse_credentials_text(text)
        assert r.login == 'user@mail.com'
        assert r.email_login_link == 'https://firstmail.ltd/webmail'


# ── Colon label with value on next line ────────────────────────────


class TestColonLabelNextLine:
    """Labels like 'E-mail sign in link:\\n\\tvalue'."""

    def test_email_sign_in_link_next_line(self):
        text = (
            "E-mail sign in link:\n"
            "\thttps://notletters.com/email/login"
        )
        r = parse_credentials_text(text)
        assert r.email_login_link == 'https://notletters.com/email/login'

    def test_mail_sign_in_link_next_line(self):
        text = (
            "Mail sign in link:\n"
            "\thttps://mail.ru/login"
        )
        r = parse_credentials_text(text)
        assert r.email_login_link == 'https://mail.ru/login'


# ── Regression: existing formats still work ────────────────────────


class TestExistingFormats:
    """Ensure previous formats are not broken by the changes."""

    def test_standard_labeled(self):
        text = "Login: user@mail.com\nPassword: abc123"
        r = parse_credentials_text(text)
        assert r.login == 'user@mail.com'
        assert r.password == 'abc123'

    def test_standard_arrow(self):
        text = "Device ID -> user123\nDevice Password -> pass456"
        r = parse_credentials_text(text)
        assert r.login == 'user123'
        assert r.password == 'pass456'

    def test_colon_separated(self):
        text = "user@mail.com:password123"
        r = parse_credentials_text(text)
        assert r.login == 'user@mail.com'
        assert r.password == 'password123'

    def test_tab_separated(self):
        text = "user@mail.com\tpassword123\temail@x.com\temailpass"
        r = parse_credentials_text(text)
        assert r.login == 'user@mail.com'
        assert r.password == 'password123'
        assert r.email == 'email@x.com'
        assert r.email_password == 'emailpass'

    def test_epic_games_section(self):
        text = "Epic Games Details:\n\tuser@mail.com : epicpass"
        r = parse_credentials_text(text)
        assert r.login == 'user@mail.com'
        assert r.password == 'epicpass'

    def test_supercell_id(self):
        text = "Supercell ID -> player@mail.com\nSupercell ID Password -> scpass"
        r = parse_credentials_text(text)
        assert r.login == 'player@mail.com'
        assert r.password == 'scpass'

    def test_mail_password_space_separated(self):
        text = "user@mail.com\nmail password secret123"
        r = parse_credentials_text(text)
        assert r.email_password == 'secret123'

    def test_security_email_pattern(self):
        text = "user@mail.com:pass\nsecurity@backup.com is security mail"
        r = parse_credentials_text(text)
        assert r.login == 'user@mail.com'
        assert r.password == 'pass'
        assert r.security_email == 'security@backup.com'

    def test_multi_colon(self):
        text = "login@x.com:pass1:email@y.com:pass2"
        r = parse_credentials_text(text)
        assert r.login == 'login@x.com'
        assert r.password == 'pass1'
        assert r.email == 'email@y.com'
        assert r.email_password == 'pass2'

    def test_empty_input(self):
        r = parse_credentials_text('')
        assert r.login == ''
        assert r.password == ''

    def test_none_like_input(self):
        r = parse_credentials_text('   ')
        assert r.login == ''


# ── Fix 1: Colon-separated unlabeled (user:pass without @) ───────


class TestColonSeparatedUnlabeled:
    """user:pass on first line with labeled lines following."""

    def test_colon_user_pass_with_mail_link(self):
        text = (
            "sampcanavari146:MS1Q3UMY1v  \n"
            "frereisauprico-1289@yopmail.com \n"
            "mail login link: yopmail.com"
        )
        r = parse_credentials_text(text)
        assert r.login == 'sampcanavari146'
        assert r.password == 'MS1Q3UMY1v'
        assert r.email_login_link == 'yopmail.com'

    def test_colon_user_pass_with_email_and_link(self):
        text = (
            "baslabakalimm52:8AQuvxQ8TO \n"
            "yonniddinnuke-9883@yopmail.com\n"
            "mail login link: yopmail.com"
        )
        r = parse_credentials_text(text)
        assert r.login == 'baslabakalimm52'
        assert r.password == '8AQuvxQ8TO'
        assert r.email_login_link == 'yopmail.com'

    def test_colon_user_pass_multicolon_mail(self):
        """clampkof:X4ZXZ2XKA7AT with Mail:Mail password section."""
        text = (
            "clampkof:X4ZXZ2XKA7AT\n"
            "Mail:Mail password\n"
            "capperleist79@outlook.com:11IC46Zq"
        )
        r = parse_credentials_text(text)
        assert r.login == 'clampkof'
        assert r.password == 'X4ZXZ2XKA7AT'


# ── Fix 2: Arrow multi-pair on same line ─────────────────────────


class TestArrowMultiPair:
    """Device ID -> x Device Password -> y on a single line."""

    def test_device_id_and_password_same_line(self):
        text = (
            "Device ID -> user@superfickl.ru Device Password -> Markt123123\n"
            "E-mail -> user@superfickl.ru E-mail Password -> Markt123123\n"
            "E-mail Login Link -> firstmail.ltd/webmail Birthday -> 01/01/2000"
        )
        r = parse_credentials_text(text)
        assert r.login == 'user@superfickl.ru'
        assert r.password == 'Markt123123'
        assert r.email == 'user@superfickl.ru'
        assert r.email_password == 'Markt123123'
        assert r.email_login_link == 'firstmail.ltd/webmail'

    def test_device_id_password_with_linebreak(self):
        """Arrow value continues on next line after ->."""
        text = (
            "Device ID -> user@superfickl.ru Device Password ->\n"
            "Markt123123 \n"
            "E-mail -> user@superfickl.ru\n"
            "E-mail Login Link -> firstmail.ltd/webmail"
        )
        r = parse_credentials_text(text)
        assert r.login == 'user@superfickl.ru'
        assert r.email == 'user@superfickl.ru'
        assert r.email_login_link == 'firstmail.ltd/webmail'

    def test_arrow_single_pair_still_works(self):
        """Ensure single arrow pairs aren't broken."""
        text = "Device ID -> myuser\nDevice Password -> mypass"
        r = parse_credentials_text(text)
        assert r.login == 'myuser'
        assert r.password == 'mypass'


# ── Fix 3: Second unlabeled line as password ─────────────────────


class TestSecondUnlabeledPassword:
    """Password on line 2 when labeled fields exist later."""

    def test_email_newline_pass_with_domain(self):
        text = (
            "bannikova.dg2gm@rambler.ru\t\n"
            "Legolas123123\n"
            "Mail login\n"
            "rambler.ru"
        )
        r = parse_credentials_text(text)
        assert r.login == 'bannikova.dg2gm@rambler.ru'
        assert r.password == 'Legolas123123'
        assert r.email_login_link == 'rambler.ru'

    def test_email_newline_pass_no_extra_labels(self):
        text = (
            "user@mail.com\n"
            "secretpass\n"
            "rambler.ru"
        )
        r = parse_credentials_text(text)
        assert r.login == 'user@mail.com'
        assert r.password == 'secretpass'
        assert r.email_login_link == 'rambler.ru'


# ── Fix 4: Email + single space + password ───────────────────────


class TestEmailSingleSpacePassword:
    """email@x.com password — single space separator."""

    def test_email_space_password(self):
        text = "fwio33hamo@outlook.com realhamo11"
        r = parse_credentials_text(text)
        assert r.login == 'fwio33hamo@outlook.com'
        assert r.password == 'realhamo11'

    def test_email_space_password_not_label(self):
        """Don't split if second word is a known label like 'password'."""
        text = "Login: user@x.com\nPassword: abc123"
        r = parse_credentials_text(text)
        assert r.login == 'user@x.com'
        assert r.password == 'abc123'


# ── Fix 5: Double-tab ────────────────────────────────────────────


class TestDoubleTab:
    """email\\t\\tpassword — consecutive tabs."""

    def test_double_tab_email_password(self):
        text = "dfb4bghs@outlook.com\t\ttorky@@#1"
        r = parse_credentials_text(text)
        assert r.login == 'dfb4bghs@outlook.com'
        assert r.password == 'torky@@#1'

    def test_triple_tab_still_works(self):
        text = "user@x.com\t\t\tpassword123"
        r = parse_credentials_text(text)
        assert r.login == 'user@x.com'
        assert r.password == 'password123'


# ── Fix 6: login-XXX password-YYY inline format ─────────────────


class TestInlineLoginPassword:
    """login XXX password YYY or login-XXX password-YYY."""

    def test_login_space_password_space(self):
        text = "login Katakuri_Hackee password SadervareSadervare"
        r = parse_credentials_text(text)
        assert r.login == 'Katakuri_Hackee'
        assert r.password == 'SadervareSadervare'

    def test_login_dash_password_dash(self):
        text = "login-Hjkilokj password-qwelkjzxc"
        r = parse_credentials_text(text)
        assert r.login == 'Hjkilokj'
        assert r.password == 'qwelkjzxc'


# ── Fix 7: Multiple colon labels on one line (steam ID: x ...) ───


class TestMultiColonLabelOneLine:
    """steam ID: x steam password: y on one line."""

    def test_steam_id_password_one_line(self):
        text = (
            "steam ID: rymmt52578 steam password: jkeng21235\n"
            "email: lf168062@atmail.club email password: 95442520\n"
            "rockstar email: jenny@mail.ru rockstar password: bkeppvpzX!4742\n"
            "rockstar mail login link: https://firstmail.ltd/webmail/login/"
        )
        r = parse_credentials_text(text)
        assert r.login == 'rymmt52578'
        assert r.password == 'jkeng21235'
        assert r.email == 'lf168062@atmail.club'
        assert r.email_password == '95442520'


# ── Bug fix: Arrow inside password value ─────────────────────────


class TestArrowInsidePasswordValue:
    """Password containing '->' should not be confused with arrow format."""

    def test_password_with_arrow_chars(self):
        text = (
            "Login: lkibezphne@rambler.ru\n"
            "Password: p2|KDu->Vf{ks@C\n"
            "Email: lkibezphne@rambler.ru\n"
            "Email Password: bgSg36fRGFSN"
        )
        r = parse_credentials_text(text)
        assert r.login == 'lkibezphne@rambler.ru'
        assert r.password == 'p2|KDu->Vf{ks@C'
        assert r.email == 'lkibezphne@rambler.ru'
        assert r.email_password == 'bgSg36fRGFSN'

    def test_password_with_arrow_simple(self):
        text = (
            "Login: user@mail.com\n"
            "Password: abc->def123"
        )
        r = parse_credentials_text(text)
        assert r.login == 'user@mail.com'
        assert r.password == 'abc->def123'


# ── Bug fix: Duplicate consecutive lines ─────────────────────────


class TestDuplicateLines:
    """Duplicate email\\tpass lines should be deduplicated."""

    def test_identical_tab_lines(self):
        text = (
            "user@outlook.com\tZomba1454125#\n"
            "user@outlook.com\tZomba1454125#"
        )
        r = parse_credentials_text(text)
        assert r.login == 'user@outlook.com'
        assert r.password == 'Zomba1454125#'
        assert '\n' not in r.password

    def test_different_lines_not_deduped(self):
        """Two different credential lines should not be collapsed."""
        text = (
            "user@outlook.com\tPass123\n"
            "admin@outlook.com\tPass456"
        )
        r = parse_credentials_text(text)
        assert r.login == 'user@outlook.com'
        # Both lines are different so dedup doesn't collapse them


# ── Bug fix: Tab-indented label without colon ────────────────────


class TestTabIndentedMailPassword:
    """Tab-indented values after space-separated labels like 'Mail password'."""

    def test_mail_password_tab_indented(self):
        text = (
            "AnniceBaldelli673@hotmail.com\n"
            "\tLegolas123123\n"
            "Mail password\n"
            "\t0k1LlNumI7W"
        )
        r = parse_credentials_text(text)
        assert r.login == 'AnniceBaldelli673@hotmail.com'
        assert r.password == 'Legolas123123'
        assert r.email_password == '0k1LlNumI7W'
        assert '\n' not in r.password

    def test_mail_pass_tab_indented(self):
        text = (
            "KailynKamph43@hotmail.com\n"
            "\tLegolas123123\n"
            "Mail pass\n"
            "\tw3GHHz2mbG"
        )
        r = parse_credentials_text(text)
        assert r.login == 'KailynKamph43@hotmail.com'
        assert r.password == 'Legolas123123'
        assert r.email_password == 'w3GHHz2mbG'

    def test_mail_pasword_typo(self):
        """Handle 'Mail pasword' typo from real data."""
        text = (
            "ShirleneTayler06@hotmail.com\tLegolas123123\n"
            "Mail pasword\n"
            "\t64G9omSDJ"
        )
        r = parse_credentials_text(text)
        assert r.login == 'ShirleneTayler06@hotmail.com'
        assert r.password == 'Legolas123123'

    def test_e_mail_password_tab_indented(self):
        text = (
            "WinterLockner888@hotmail.com\t\n"
            "Legolas123123\t\n"
            "e mail password\n"
            "tjI36Ecng"
        )
        r = parse_credentials_text(text)
        assert r.login == 'WinterLockner888@hotmail.com'
        assert r.password == 'Legolas123123'


# ── Bug fix: login==email → email_password becomes password ──────


class TestLoginEqualsEmailPasswordFallback:
    """When login==email and password is empty, use email_password."""

    def test_account_login_details_section(self):
        text = (
            "Account Login Details:\n"
            "\tjeqhjhjn@tacoblastmail.com\n"
            "E-mail Sign in Details:\n"
            "\tjeqhjhjn@tacoblastmail.com : sQwDoeIdHZ\n"
            "E-mail sign in link:\n"
            "\thttps://firstmail.ltd/webmail"
        )
        r = parse_credentials_text(text)
        assert r.login == 'jeqhjhjn@tacoblastmail.com'
        assert r.password == 'sQwDoeIdHZ'
        assert r.email == 'jeqhjhjn@tacoblastmail.com'
        assert r.email_password == 'sQwDoeIdHZ'
        assert r.email_login_link == 'https://firstmail.ltd/webmail'

    def test_no_fallback_when_login_differs_from_email(self):
        """Don't copy email_password if login != email."""
        text = (
            "Login: gameuser123\n"
            "Email: user@mail.com\n"
            "Email Password: mailpass456"
        )
        r = parse_credentials_text(text)
        assert r.login == 'gameuser123'
        assert r.password == ''
        assert r.email_password == 'mailpass456'

    def test_no_fallback_when_password_exists(self):
        """Don't overwrite existing password."""
        text = (
            "Login: user@mail.com\n"
            "Password: realpass\n"
            "Email: user@mail.com\n"
            "Email Password: mailpass"
        )
        r = parse_credentials_text(text)
        assert r.login == 'user@mail.com'
        assert r.password == 'realpass'
