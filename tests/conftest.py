import shutil
from pathlib import Path

import pytest
import yaml

from core.config import DEFAULT_CONFIG_DIR, load_config


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture
def config_copy(tmp_path: Path):
    """A writable copy of data/config for tests that mutate config."""
    dst = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, dst)

    def edit(fname: str, fn):
        p = dst / fname
        data = yaml.safe_load(p.read_text())
        fn(data)
        p.write_text(yaml.safe_dump(data, sort_keys=False))

    return dst, edit


@pytest.fixture
def lot():
    """Parcel-shaped dict (fields only; not a real parcel)."""
    return {"id": "TEST", "lot_area_sf": 5000, "land_value_usd": 10000, "zoning": "TEST-D",
            "neighborhood": "Test", "steep_slope": True, "landslide": False, "undermined": None}
