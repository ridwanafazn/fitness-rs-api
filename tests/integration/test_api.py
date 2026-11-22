from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.mark.integration
def test_health_and_readiness(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    ready = client.get("/ready")
    assert ready.status_code == 200
    body = ready.json()
    assert body["status"] == "ready"
    assert body["dataset_size"] == 222
    assert len(body["dataset_version"]) == 16


@pytest.mark.integration
def test_valid_recommendation(client, valid_payload):
    response = client.post("/api/v1/recommendation/", json=valid_payload)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["split_type"] == "upperlower"
    assert len(body["days"]) == 2
    assert body["seed"] == 42
    assert body["dataset_version"]
    assert body["algorithm_version"] == "2.0.0"
    assert set(body["schedule"]) == {"day_1", "day_2"}

    for day in body["days"]:
        assert day["exercises"]
        ids = [exercise["exercise_id"] for exercise in day["exercises"]]
        assert len(ids) == len(set(ids))
        for exercise in day["exercises"]:
            assert exercise["image_url"]
            assert isinstance(exercise["equipment"], list)


@pytest.mark.integration
def test_settings_seed_is_used_when_request_has_no_seed(dataset_path: Path):
    settings = Settings(
        environment="test",
        dataset_path=dataset_path,
        rate_limit_enabled=False,
        metrics_enabled=False,
        ga_random_seed=123,
        ga_num_generations=5,
        ga_sol_per_pop=8,
        ga_num_parents_mating=4,
        ga_keep_parents=2,
    )
    app = create_app(settings)
    payload = {
        "gender": "male",
        "height_cm": 175,
        "weight_kg": 72,
        "available_days": 1,
    }
    with TestClient(app) as client:
        response = client.post("/api/v1/recommendation/", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["seed"] == 123


@pytest.mark.integration
def test_same_seed_produces_same_response(client, valid_payload):
    first = client.post("/api/v1/recommendation/", json=valid_payload)
    second = client.post("/api/v1/recommendation/", json=valid_payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


@pytest.mark.integration
def test_injured_body_part_never_appears_in_output(client, valid_payload):
    payload = {
        **valid_payload,
        "injuries": ["lower back"],
        "available_days": 2,
    }
    response = client.post("/api/v1/recommendation/", json=payload)
    assert response.status_code == 200, response.text
    forbidden = {"back", "glutes", "hamstrings"}
    for day in response.json()["days"]:
        for exercise in day["exercises"]:
            assert exercise["body_part"] not in forbidden


@pytest.mark.integration
def test_knee_injury_adapts_leg_day_instead_of_failing_whole_plan(client, valid_payload):
    payload = {
        **valid_payload,
        "injuries": ["knee"],
        "available_days": 3,
        "seed": 7,
    }
    response = client.post("/api/v1/recommendation/", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["days"]) == 3
    assert body["warnings"]
    forbidden = {"quadriceps", "hamstrings", "glutes", "calves"}
    for day in body["days"]:
        for exercise in day["exercises"]:
            assert exercise["body_part"] not in forbidden


@pytest.mark.integration
def test_by_focus_chest_returns_only_chest(client):
    response = client.post(
        "/api/v1/recommendation/by-focus",
        json={"day_focus": "chest", "seed": 7},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["day_focus"] == "chest"
    assert len(body["exercises"]) == 4
    assert all(exercise["body_part"] == "chest" for exercise in body["exercises"])


@pytest.mark.integration
def test_by_focus_injured_area_fails_without_unsafe_fallback(client):
    response = client.post(
        "/api/v1/recommendation/by-focus",
        json={"day_focus": "chest", "injuries": ["chest"], "seed": 7},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "insufficient_exercise_pool"
    assert body["request_id"]
    assert "exercises" not in body


@pytest.mark.integration
@pytest.mark.parametrize(
    "override",
    [
        {"gender": "other"},
        {"available_days": 6},
        {"available_days": 0},
        {"injuries": ["broken_soul"]},
        {"preferred_equipment": ["spaceship"]},
        {"preferred_body_part": ["lower back"]},
        {"height_cm": 10},
        {"weight_kg": 1000},
        {"unknown_field": True},
    ],
)
def test_invalid_payload_is_rejected(client, valid_payload, override):
    payload = {**valid_payload, **override}
    response = client.post("/api/v1/recommendation/", json=payload)
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["request_id"]
    assert body["error"]["details"]


@pytest.mark.integration
def test_security_headers(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


@pytest.mark.integration
def test_invalid_request_id_header_is_replaced(client):
    response = client.get("/health", headers={"X-Request-ID": "x" * 100})
    assert response.status_code == 200
    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32


@pytest.mark.integration
def test_request_id_header_and_error_envelope(client, valid_payload):
    response = client.post(
        "/api/v1/recommendation/",
        json={**valid_payload, "gender": "other"},
    )
    assert response.status_code == 422
    assert response.headers["X-Request-ID"] == response.json()["request_id"]


@pytest.mark.integration
def test_api_key_is_enforced_when_configured(dataset_path: Path):
    settings = Settings(
        environment="test",
        dataset_path=dataset_path,
        api_key="secret-key",
        rate_limit_enabled=False,
        metrics_enabled=False,
        ga_num_generations=5,
        ga_sol_per_pop=8,
        ga_num_parents_mating=4,
        ga_keep_parents=2,
    )
    app = create_app(settings)
    payload = {
        "gender": "male",
        "height_cm": 175,
        "weight_kg": 72,
        "available_days": 1,
        "seed": 1,
    }
    with TestClient(app) as client:
        assert client.post("/api/v1/recommendation/", json=payload).status_code == 401
        authorized = client.post(
            "/api/v1/recommendation/",
            json=payload,
            headers={"X-API-Key": "secret-key"},
        )
        assert authorized.status_code == 200, authorized.text


@pytest.mark.integration
def test_metrics_endpoint_when_enabled(dataset_path: Path):
    settings = Settings(
        environment="test",
        dataset_path=dataset_path,
        rate_limit_enabled=False,
        metrics_enabled=True,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "http_requests" in response.text or "python_gc" in response.text


@pytest.mark.integration
def test_cors_allowlist(dataset_path: Path):
    settings = Settings(
        environment="test",
        dataset_path=dataset_path,
        rate_limit_enabled=False,
        metrics_enabled=False,
        cors_origins="https://frontend.example",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/recommendation/",
            headers={
                "Origin": "https://frontend.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://frontend.example"


@pytest.mark.integration
def test_request_body_limit(dataset_path: Path):
    settings = Settings(
        environment="test",
        dataset_path=dataset_path,
        rate_limit_enabled=False,
        metrics_enabled=False,
        max_request_bytes=200,
        ga_num_generations=5,
        ga_sol_per_pop=8,
        ga_num_parents_mating=4,
        ga_keep_parents=2,
    )
    app = create_app(settings)
    payload = {
        "gender": "male",
        "height_cm": 175,
        "weight_kg": 72,
        "available_days": 1,
        "seed": 1,
        "padding": "x" * 1000,
    }
    with TestClient(app) as client:
        response = client.post("/api/v1/recommendation/", json=payload)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_too_large"


@pytest.mark.integration
def test_rate_limit_returns_429(dataset_path: Path):
    settings = Settings(
        environment="test",
        dataset_path=dataset_path,
        rate_limit_enabled=True,
        rate_limit="1/minute",
        rate_limit_storage_uri="memory://",
        metrics_enabled=False,
        ga_num_generations=5,
        ga_sol_per_pop=8,
        ga_num_parents_mating=4,
        ga_keep_parents=2,
    )
    app = create_app(settings)
    payload = {
        "gender": "male",
        "height_cm": 175,
        "weight_kg": 72,
        "available_days": 1,
        "seed": 1,
    }
    with TestClient(app) as client:
        assert client.post("/api/v1/recommendation/", json=payload).status_code == 200
        limited = client.post("/api/v1/recommendation/", json=payload)
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "rate_limit_exceeded"
