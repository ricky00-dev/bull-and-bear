from bullbear.config import Settings


def test_statement_review_defaults_on_and_can_be_disabled(monkeypatch):
    from bullbear.config import load_settings
    from bullbear.server.service import LiveRunner
    monkeypatch.delenv('BULLBEAR_REVIEW_STATEMENTS', raising=False)
    settings = load_settings()
    assert settings.review_statements and LiveRunner(settings).review_statements
    assert not LiveRunner(settings, review_statements=False).review_statements
    monkeypatch.setenv('BULLBEAR_REVIEW_STATEMENTS', 'false')
    disabled = load_settings()
    assert not LiveRunner(disabled).review_statements
    assert LiveRunner(disabled, review_statements=True).review_statements


def test_settings_repr_omits_credentials(tmp_path):
    settings = Settings(model='test-model', dart_api_key='private-dart',
                        naver_client_id='private-id', naver_client_secret='private-secret',
                        krx_api_key='private-krx', data_dir=tmp_path,
                        debater_effort='medium', moderator_effort='high')
    assert 'private-' not in repr(settings)
    assert 'test-model' in repr(settings)
