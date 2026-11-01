"""Read-only HTTP worker configuration check; never calls a model or provider."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .audit import selected_models
from .config import load_settings
from .llm import validate_model


def inspect_settings(settings) -> dict:
    errors, warnings = [], []
    models = selected_models(settings)
    safe_models = {}
    for role, model in models.items():
        try:
            validate_model(model)
            safe_models[role] = model
        except ValueError:
            safe_models[role] = None
            errors.append(f'{role}_model_not_allowed')
    credentials = {
        'ANTHROPIC_API_KEY': bool(os.getenv('ANTHROPIC_API_KEY', '').strip()),
        'KRX_API_KEY': bool(settings.krx_api_key),
        'OPENDART_API_KEY': bool(settings.dart_api_key),
        'NAVER_CLIENT_ID': bool(settings.naver_client_id),
        'NAVER_CLIENT_SECRET': bool(settings.naver_client_secret),
        'WORKER_TOKEN': bool(os.getenv('WORKER_TOKEN', '').strip()),
    }
    for key in ('ANTHROPIC_API_KEY', 'KRX_API_KEY', 'WORKER_TOKEN'):
        if not credentials[key]:
            errors.append(f'missing_{key}')
    if os.getenv('WORKER_TOKEN') == 'dev-worker-token':
        errors.append('development_worker_token')
    for key in ('OPENDART_API_KEY', 'NAVER_CLIENT_ID', 'NAVER_CLIENT_SECRET'):
        if not credentials[key]:
            warnings.append(f'missing_optional_{key}')
    if settings.rag_shadow_enabled:
        if not settings.rag_enabled:
            warnings.append('shadow_requires_primary_rag')
        if not settings.rag_shadow_spec or not settings.rag_postgres_dsn:
            warnings.append('shadow_configuration_missing')
        if settings.rag_shadow_prepare_query and settings.rag_shadow_daily_budget_nano <= 0:
            warnings.append('shadow_query_budget_missing')
        warnings.append('shadow_is_private_observation_only')
    if settings.rag_enabled:
        if settings.rag_archive_backend not in {'sqlite', 'postgres'}:
            errors.append('unsupported_rag_archive_backend')
        if settings.rag_archive_backend == 'postgres' and not settings.rag_postgres_dsn:
            errors.append('missing_rag_archive_dsn')
        if settings.rag_object_backend not in {'local', 's3'}:
            errors.append('unsupported_rag_object_backend')
        if settings.rag_object_backend == 's3' and not settings.rag_s3_bucket:
            errors.append('missing_rag_s3_bucket')
        if settings.rag_context_backend not in {'sqlite', 'postgres'}:
            errors.append('unsupported_rag_context_backend')
        elif settings.rag_context_backend == 'postgres' and not settings.rag_postgres_dsn:
            errors.append('missing_rag_postgres_dsn')
        if not settings.rag_generation_id:
            errors.append('missing_rag_generation')
        if settings.rag_profile != 'knowledge-short-v1':
            errors.append('unsupported_rag_profile')
        warnings.append('rag_requires_separate_operational_acceptance')
    return {
        'provider': 'anthropic', 'models': safe_models, 'automatic_model_fallback': False,
        'credentials_present': credentials, 'rag_enabled': settings.rag_enabled,
        'configuration_ready': not errors, 'errors': errors, 'warnings': warnings,
        'network_calls': 0, 'model_access_verified': False,
        'data_sources_verified': False, 'operational_readiness_verified': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path,
                        help='Explicit dotenv file; overrides inherited values in this process only')
    args = parser.parse_args()
    if args.env_file:
        if not args.env_file.is_file():
            parser.exit(2, 'Environment file not found; no calls made.\n')
        load_dotenv(args.env_file, override=True)
    report = inspect_settings(load_settings())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['configuration_ready'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
