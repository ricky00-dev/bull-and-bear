import json

from bullbear.config import load_settings
from bullbear.preflight import inspect_settings


def configured(monkeypatch):
    monkeypatch.setattr('bullbear.config.load_dotenv', lambda: None)
    for key in ('BULLBEAR_MODEL', 'BULLBEAR_DEBATER_MODEL', 'BULLBEAR_MODERATOR_MODEL',
                'BULLBEAR_WORKER_BUDGET_USD', 'BULLBEAR_WORKER_BUDGET_ID'):
        monkeypatch.delenv(key, raising=False)
    for key in ('ANTHROPIC_API_KEY', 'KRX_API_KEY', 'OPENDART_API_KEY',
                'NAVER_CLIENT_ID', 'NAVER_CLIENT_SECRET', 'WORKER_TOKEN'):
        monkeypatch.setenv(key, 'private-test-value')
    return load_settings()


def test_default_roles_and_no_secret_values(monkeypatch):
    report = inspect_settings(configured(monkeypatch))
    assert report['models'] == {'debater': 'claude-sonnet-5-5', 'moderator': 'claude-sonnet-5-5'}
    assert report['configuration_ready']
    assert 'private-test-value' not in json.dumps(report)
    assert not report['model_access_verified']
    assert not report['operational_readiness_verified']
    assert 'worker_provider_budget_not_configured' in report['warnings']


def test_old_opus_override_and_missing_key_block_readiness(monkeypatch):
    configured(monkeypatch)
    monkeypatch.setenv('BULLBEAR_MODEL', 'claude-opus-5-5')
    monkeypatch.delenv('ANTHROPIC_API_KEY')
    report = inspect_settings(load_settings())
    assert not report['configuration_ready']
    assert set(report['errors']) == {'debater_model_not_allowed', 'moderator_model_not_allowed',
                                     'missing_ANTHROPIC_API_KEY'}


def test_role_overrides(monkeypatch):
    configured(monkeypatch)
    monkeypatch.setenv('BULLBEAR_DEBATER_MODEL', 'claude-sonnet-5-5')
    monkeypatch.setenv('BULLBEAR_MODERATOR_MODEL', 'claude-haiku-5-5')
    report = inspect_settings(load_settings())
    assert report['models']['moderator'] == 'claude-haiku-5-5'
    assert report['configuration_ready']
    assert report['network_calls'] == 0


def test_budget_configuration_check_is_read_only_and_needs_both_fields(monkeypatch, tmp_path):
    configured(monkeypatch)
    monkeypatch.setenv('BULLBEAR_DATA_DIR', str(tmp_path/'no-data'))
    monkeypatch.setenv('BULLBEAR_WORKER_BUDGET_USD', '3')
    report = inspect_settings(load_settings())
    assert 'invalid_worker_budget_configuration' in report['errors']
    monkeypatch.setenv('BULLBEAR_WORKER_BUDGET_ID', 'approved-pilot')
    report = inspect_settings(load_settings())
    assert report['configuration_ready'] and report['worker_budget_limit_usd'] == 3
    assert not report['worker_budget_state_verified'] and report['network_calls'] == 0
    assert not (tmp_path/'no-data').exists()
