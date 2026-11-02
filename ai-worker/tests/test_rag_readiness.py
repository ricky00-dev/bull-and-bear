from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import pytest
from bullbear.config import load_settings
from bullbear.rag.cli import main
from bullbear.rag.index import GenerationIndex
from bullbear.rag.readiness import check_generation, require_ready_generation
from bullbear.rag.store import RagStore, ArchiveCorruptError
from .test_rag_evidence import snapshot
from .test_rag_retrieval import seed


def test_publication_precedes_new_snapshots_without_changing_history(tmp_path, capsys):
    with RagStore(tmp_path / 'rag') as store:
        seed(store)
        generation = GenerationIndex(store).publish(datetime.now(timezone.utc))
        ready = check_generation(store, generation)
        committed = datetime.fromisoformat(ready['committed_at'])
        old = snapshot().model_copy(update={'created_at': committed - timedelta(seconds=1)})
        new = snapshot().model_copy(update={'snapshot_id': 'new', 'created_at': committed + timedelta(seconds=1)})
        before = old.model_dump_json()
        report = check_generation(store, generation, snapshots=[old, new])
        assert report['ready_for_new_snapshot']
        assert not report['all_snapshots_eligible']
        assert not report['snapshots'][0]['eligible'] and report['snapshots'][1]['eligible']
        assert 'generation_not_committed_at_decision' in report['snapshots'][0]['reasons']
        assert old.model_dump_json() == before
        later = GenerationIndex(store).publish(datetime.now(timezone.utc) + timedelta(days=1))
        assert not check_generation(store, later)['ready_for_new_snapshot']
    path = tmp_path / 'snapshot.json'
    path.write_text(old.model_dump_json(), encoding='utf-8')
    assert main(['--data-dir', str(tmp_path), 'check-generation', '--generation', generation, '--snapshot', str(path)]) == 1
    assert not json.loads(capsys.readouterr().out)['all_snapshots_eligible']
    settings = replace(load_settings(), data_dir=tmp_path, rag_archive_backend='sqlite', rag_object_backend='local', rag_generation_id=generation)
    assert require_ready_generation(settings)['ready_for_new_snapshot']
    with pytest.raises(ValueError):
        require_ready_generation(replace(settings, rag_generation_id=later))
    with pytest.raises(ValueError):
        require_ready_generation(replace(settings, rag_generation_id=None))


def test_readiness_checks_actual_file_integrity(tmp_path):
    with RagStore(tmp_path) as store:
        generation = GenerationIndex(store).publish(datetime.now(timezone.utc))
        path = GenerationIndex(store).path(generation)
        with path.open('ab') as stream:
            stream.write(b'corrupt')
        with pytest.raises(ArchiveCorruptError):
            check_generation(store, generation)


def test_new_publication_does_not_replace_generation_for_old_snapshot(tmp_path):
    with RagStore(tmp_path) as store:
        seed(store)
        first = GenerationIndex(store).publish(datetime.now(timezone.utc))
        frozen = snapshot().model_copy(update={'created_at': datetime.now(timezone.utc)})
        second = GenerationIndex(store).publish(datetime.now(timezone.utc))
        assert first != second
        assert check_generation(store, first, snapshots=[frozen])['all_snapshots_eligible']
        assert not check_generation(store, second, snapshots=[frozen])['all_snapshots_eligible']
