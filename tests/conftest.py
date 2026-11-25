import copy;
import pytest;
import GUI_menus.settings_store as settings_store;
from pathlib import Path;

#Stores the original settings save function so it can be retained from changes during testing and mocking.
#This allows us to directly test save().
_REAL_SAVE = settings_store.save;

@pytest.fixture()
def real_save():
    return _REAL_SAVE;

@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path: Path):
    record = {"save_calls": 0};
    
    def fake_save():
        record["save_calls"] += 1;
        return True;
    
    monkeypatch.setattr(settings_store, "SETTINGS", copy.deepcopy(settings_store.DEFAULTS));
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", str((tmp_path / "settings.json")));
    monkeypatch.setattr(settings_store, "save", fake_save);
    return record;
