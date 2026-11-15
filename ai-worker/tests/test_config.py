from bullbear.config import Settings


def test_settings_repr_omits_credentials(tmp_path):
    settings = Settings(model='test-model', dart_api_key='private-dart',
                        naver_client_id='private-id', naver_client_secret='private-secret',
                        krx_api_key='private-krx', data_dir=tmp_path,
                        debater_effort='medium', moderator_effort='high')
    assert 'private-' not in repr(settings)
    assert 'test-model' in repr(settings)
