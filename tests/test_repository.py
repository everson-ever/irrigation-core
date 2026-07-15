import json
import os

import pytest

from irrigation.domain.exceptions import RecordNotFoundError, ValidationError
from irrigation.infrastructure.json_repository import JsonLinesRepository


def test_crud_preserves_valid_json_lines(tmp_path):
    file_path = tmp_path / "records.json"
    repository = JsonLinesRepository(file_path)

    first = repository.add({"nome": "Seção 1"})
    second = repository.add({"nome": "Seção 2"})
    first["nome"] = "Atualizada"
    repository.update(first)
    repository.delete([second["id"]])

    assert repository.list_all() == [{"id": "1", "nome": "Atualizada"}]
    assert [json.loads(line) for line in file_path.read_text().splitlines()] == [
        {"id": "1", "nome": "Atualizada"}
    ]


def test_update_missing_id_fails(tmp_path):
    repository = JsonLinesRepository(tmp_path / "records.json")

    with pytest.raises(RecordNotFoundError):
        repository.update({"id": "9"})


def test_cache_sees_writes_from_other_process(tmp_path):
    file_path = tmp_path / "records.json"
    reader = JsonLinesRepository(file_path)
    writer = JsonLinesRepository(file_path)

    assert reader.list_all() == []
    writer.add({"nome": "Seção 1"})
    assert reader.list_all() == [{"id": "1", "nome": "Seção 1"}]
    writer.update({"id": "1", "nome": "Atualizada"})
    assert reader.list_all() == [{"id": "1", "nome": "Atualizada"}]


def test_mutating_results_does_not_corrupt_cache(tmp_path):
    repository = JsonLinesRepository(tmp_path / "records.json")
    repository.add({"nome": "Seção 1"})

    repository.list_all()[0]["nome"] = "mutada"
    assert repository.list_all() == [{"id": "1", "nome": "Seção 1"}]


def test_add_appends_without_rewriting_the_file(tmp_path):
    file_path = tmp_path / "records.json"
    repository = JsonLinesRepository(file_path)
    repository.add({"nome": "Seção 1"})

    inode_before = os.stat(file_path).st_ino
    repository.add({"nome": "Seção 2"})
    assert os.stat(file_path).st_ino == inode_before
    assert [json.loads(line) for line in file_path.read_text().splitlines()] == [
        {"nome": "Seção 1", "id": "1"},
        {"nome": "Seção 2", "id": "2"},
    ]


def test_torn_final_line_is_tolerated_and_repaired_by_add(tmp_path):
    file_path = tmp_path / "records.json"
    repository = JsonLinesRepository(file_path)
    repository.add({"nome": "Seção 1"})
    # Simulate a crash mid-append: partial line without trailing newline.
    with file_path.open("ab") as file:
        file.write(b'{"id": "2", "no')

    reader = JsonLinesRepository(file_path)
    assert reader.list_all() == [{"id": "1", "nome": "Seção 1"}]
    reader.add({"nome": "Seção 2"})
    assert [json.loads(line) for line in file_path.read_text().splitlines()] == [
        {"id": "1", "nome": "Seção 1"},
        {"nome": "Seção 2", "id": "2"},
    ]


def test_valid_final_line_without_newline_is_kept(tmp_path):
    file_path = tmp_path / "records.json"
    file_path.write_bytes(b'{"id": "1", "nome": "Se\xc3\xa7\xc3\xa3o 1"}')

    repository = JsonLinesRepository(file_path)
    assert repository.list_all() == [{"id": "1", "nome": "Seção 1"}]
    repository.add({"nome": "Seção 2"})
    assert repository.list_all() == [
        {"id": "1", "nome": "Seção 1"},
        {"nome": "Seção 2", "id": "2"},
    ]


def test_corruption_in_the_middle_still_fails(tmp_path):
    file_path = tmp_path / "records.json"
    file_path.write_text('{"id": "1"}\nlixo\n{"id": "2"}\n')

    with pytest.raises(ValidationError):
        JsonLinesRepository(file_path).list_all()
