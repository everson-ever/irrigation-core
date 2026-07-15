import json

from irrigacao.infrastructure.legacy_migration import migrate_part_7


def test_migration_normalizes_led_and_resets_state(tmp_path):
    source = tmp_path / "legado"
    target = tmp_path / "novo"
    source.mkdir()
    (source / "agendamentos.json").write_text(
        json.dumps(
            {
                "id": "4",
                "horario": "08:00",
                "tempoLigado": "5",
                "led": "13",
                "status": "1",
                "ativado": "1",
            }
        )
        + "\n"
    )
    (source / "valvulas.json").write_text(
        json.dumps({"id": "2", "valvula": "13", "status": 1, "secao": "Horta"}) + "\n"
    )
    (source / "configuracoes.json").write_text('{"id": "1", "tempoPadrao": 5}\n')

    totals = migrate_part_7(source, target)

    schedule = json.loads((target / "agendamentos.json").read_text())
    valve = json.loads((target / "valvulas.json").read_text())
    assert totals["agendamentos"] == 1
    assert schedule["id"] == "4"
    assert schedule["valvula"] == "13"
    assert "led" not in schedule
    assert schedule["status"] == 0
    assert valve["status"] == 0
