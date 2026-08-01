from auth_routes import _hint_from_users

GOOGLE_USER = {"email": "a@b.com", "app_metadata": {"providers": ["google"]}}
PASSWORD_USER = {"email": "a@b.com", "app_metadata": {"providers": ["email", "google"]}}


def test_oauth_only_account_returns_providers():
    assert _hint_from_users([GOOGLE_USER], "a@b.com") == ["google"]


def test_password_capable_account_returns_nothing():
    assert _hint_from_users([PASSWORD_USER], "a@b.com") == []


def test_fuzzy_filter_matches_require_exact_email():
    # GoTrue's ?filter= is a substring search — a@b.com must not match xa@b.com
    assert _hint_from_users([{"email": "xa@b.com", "app_metadata": {"providers": ["google"]}}], "a@b.com") == []


def test_unknown_email_returns_nothing():
    assert _hint_from_users([], "a@b.com") == []


def test_email_match_is_case_insensitive():
    assert _hint_from_users([{"email": "A@B.com", "app_metadata": {"providers": ["azure"]}}], "a@b.com") == ["azure"]
