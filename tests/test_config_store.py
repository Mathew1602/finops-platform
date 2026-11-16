import pytest

from finops import config_store as C


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(C.A, "SCENARIO_DIR", tmp_path / "scenarios")
    return tmp_path / "scenarios"


def test_examples_seeded_once_and_not_after_delete(store):
    names = C.list_scenarios()
    assert len(names) == 3
    for n in names:
        C.delete_scenario(n)
    assert C.list_scenarios() == []
    C.restore_examples()
    assert len(C.list_scenarios()) == 3


def test_name_collisions(store):
    C.save_scenario(C.new_scenario("Dev Small"))
    assert C.name_taken("dev-small")                      # same file, different spelling
    assert not C.name_taken("Dev Small", current="Dev Small")
    assert C.unique_name("Dev Small") == "Dev Small (2)"
    assert C.unique_name("Other") == "Other"
