import pytest

from walkforward.data import add_session_columns
from walkforward.synthetic import synthetic_minute_bars


@pytest.fixture(scope="session")
def bars():
    return add_session_columns(synthetic_minute_bars(12, seed=3))
