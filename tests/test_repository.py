import json

import pytest

from irrigacao.domain.exceptions import RecordNotFoundError
from irrigacao.infrastructure.json_repository import JsonLinesRepository


def test_crud_preserves_valid_json_lines(tmp_path):
    file_path = tmp_path / "dados.json"
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
    repository = JsonLinesRepository(tmp_path / "dados.json")

    with pytest.raises(RecordNotFoundError):
        repository.update({"id": "9"})
