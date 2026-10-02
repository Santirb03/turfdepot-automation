import pytest
from pydantic import ValidationError

from turfdepot.core.config import Settings


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "0.001"])
def test_invalid_prices(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, garden_prices={"test": value})


def test_reject_sqlite():
    with pytest.raises(ValueError):
        Settings(_env_file=None, database_url="sqlite://").connection_url()
