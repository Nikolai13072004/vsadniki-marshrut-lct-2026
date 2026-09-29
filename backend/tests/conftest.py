import pytest

from app.importer import defaults
from app.models import Dataset, Engineer, Job, Location


@pytest.fixture
def sample():
    loc = Location(latitude=55.7, longitude=37.7)
    return Dataset(
        id="test",
        name="Тестовый день",
        region="Тест",
        office_address="Москва, офис",
        office_location=loc,
        settings=defaults(),
        engineers=[
            Engineer(
                id="e1",
                name="Анна",
                start_location=loc,
                skills=["local", "connection", "emergency"],
                shift_start=540,
                shift_end=1080,
            ),
            Engineer(
                id="e2",
                name="Борис",
                start_location=loc,
                skills=["local"],
                transport="bicycle",
                shift_start=540,
                shift_end=1080,
            ),
        ],
        jobs=[
            Job(
                id=f"j{i}",
                source_id=str(i),
                address=f"Москва, объект {i}",
                location=Location(latitude=55.7 + i * 0.005, longitude=37.7),
                geo_quality="verified",
                work_type="Информация",
                duration_minutes=30,
                required_skill="local",
                window_start=600 + i * 30,
                window_end=900,
            )
            for i in range(5)
        ],
    )
