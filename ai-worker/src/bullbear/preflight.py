"""Read-only HTTP worker configuration check; never calls a model or provider."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .audit import selected_models
from .config import load_settings
from .llm import LLMRequestBlocked, validate_model, validate_snapshot_model
from .budget import amount_nano
from .anthropic_budget import POLICY
import re


def inspect_settings(settings) -> dict:
    errors, warnings = [], []
    models = selected_models(settings)
    safe_models = {}
    for role, model in models.items():
        try:
            validate_model(model)
            safe_models[role] = model
            validate_snapshot_model(model)
        except LLMRequestBlocked:
            errors.append(f'{role}_model_missing_trailing_system_support')
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
    worker_budget = settings.worker_budget_usd is not None or settings.worker_budget_id is not None
    budget_limit = None
    if worker_budget:
        try:
            budget_limit = amount_nano(settings.worker_budget_usd) / 1_000_000_000
            if not re.fullmatch(r'[A-Za-z0-9._-]{1,100}', settings.worker_budget_id or ''):
                raise ValueError('invalid id')
        except (ValueError, TypeError):
            errors.append('invalid_worker_budget_configuration')
        if any(model not in POLICY['rates_nano'] for model in models.values()):
            errors.append('worker_budget_model_not_priced')
    else:
        warnings.append('worker_provider_budget_not_configured')
        if (settings.data_dir / 'http' / 'provider-budget.sqlite3').exists():
            errors.append('worker_budget_configuration_missing_for_existing_ledger')
    for key in ('OPENDART_API_KEY', 'NAVER_CLIENT_ID', 'NAVER_CLIENT_SECRET'):
        if not credentials[key]:
            warnings.append(f'missing_optional_{key}')
    return {
        'provider': 'anthropic', 'models': safe_models, 'automatic_model_fallback': False,
        'credentials_present': credentials,
        'configuration_ready': not errors, 'errors': errors, 'warnings': warnings,
        'network_calls': 0, 'model_access_verified': False,
        'worker_budget_configured': worker_budget, 'worker_budget_limit_usd': budget_limit,
        'worker_budget_state_verified': False,
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
