from translatorx.settings import _model_endpoint, _parse_model_ids, _protect_secret, _unprotect_secret


def test_saved_secret_is_encrypted_and_can_be_restored():
    secret = "sk-test-密钥-123"
    protected = _protect_secret(secret)
    assert secret not in protected
    assert _unprotect_secret(protected) == secret


def test_invalid_saved_secret_is_ignored():
    assert _unprotect_secret("not valid dpapi data") == ""


def test_model_listing_parser_and_endpoint_are_compatible():
    assert _model_endpoint("https://example.test/v1/chat/completions") == "https://example.test/v1/models"
    assert _parse_model_ids({"data": [{"id": "z"}, {"id": "a"}, {"id": "z"}]}) == ["a", "z"]
    assert _parse_model_ids({"models": ["custom-model"]}) == ["custom-model"]
