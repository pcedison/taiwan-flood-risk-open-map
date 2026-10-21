import pytest

from app.core import config

SHA_NAMES = (
    "DEPLOYMENT_SHA", "GIT_COMMIT_SHA", "COMMIT_SHA", "SOURCE_COMMIT",
    "ZEABUR_GIT_COMMIT_SHA", "ZB_GIT_COMMIT_SHA", "VERCEL_GIT_COMMIT_SHA",
)


@pytest.fixture(autouse=True)
def clear_identity(monkeypatch):
    for name in (*SHA_NAMES, "IMAGE_SOURCE_SHA"):
        monkeypatch.delenv(name, raising=False)


def test_build_only_identity_survives_absent_runtime_metadata(monkeypatch):
    monkeypatch.setenv("IMAGE_SOURCE_SHA", "A" * 40)
    assert config._deployment_sha() == "a" * 40


@pytest.mark.parametrize("name", SHA_NAMES)
def test_runtime_identity_precedes_built_identity(monkeypatch, name):
    monkeypatch.setenv("IMAGE_SOURCE_SHA", "a" * 40)
    monkeypatch.setenv(name, "b" * 40)
    assert config._deployment_sha() == "b" * 40


@pytest.mark.parametrize("value", ["", "secret", "a" * 39, "g" * 40, "${COMMIT_SHA}"])
def test_invalid_build_identity_is_not_reported(monkeypatch, value):
    monkeypatch.setenv("IMAGE_SOURCE_SHA", value)
    assert config._deployment_sha() is None


def test_missing_build_identity_remains_unknown():
    assert config._deployment_sha() is None
