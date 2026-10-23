import json
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


def test_rundown_persistence_and_websocket_commands():
    rundown = json.loads(
        (Path(__file__).parents[2] / "Residencia-Globo-Front/src/data/stories.json").read_text()
    )
    rundown[0]["sourceSlug"] = "RUNDOWN-001"
    rundown[0]["pages"][0]["durationSeconds"] = 15
    try:
        with TestClient(app) as client:
            assert client.get("/api/health").json()["status"] == "ok"

            imported = client.post(
                "/api/sessions/integration-test/rundown",
                json={"stories": rundown},
            )
            assert imported.status_code == 200
            assert imported.json()["storiesImported"] == len(rundown)
            assert imported.json()["pagesImported"] == sum(
                len(story["pages"]) for story in rundown
            )

            with (
                client.websocket_connect("/ws/integration-test") as operator,
                client.websocket_connect("/ws/integration-test") as presenter,
            ):
                welcome = operator.receive_json()
                presenter.receive_json()
                assert welcome["state"]["editorialStories"][0]["headline"] == rundown[0]["headline"]
                operator.send_json({"type": "command", "command": "next"})
                advanced = operator.receive_json()
                presenter_advanced = presenter.receive_json()
                assert advanced["type"] == "command"
                assert advanced["state"]["pageIndex"] == 1
                assert presenter_advanced["state"]["pageIndex"] == 1

                operator.send_json({"type": "command", "command": "pause"})
                paused = operator.receive_json()
                presenter_paused = presenter.receive_json()
                assert paused["state"]["paused"] is True
                assert presenter_paused["state"]["paused"] is True

            persisted = client.get("/api/sessions/integration-test/state").json()["state"]
            assert persisted["pageIndex"] == 1
            assert persisted["paused"] is True
            assert persisted["editorialStories"][1]["headline"] == rundown[1]["headline"]
            assert persisted["editorialStories"][0]["sourceSlug"] == "RUNDOWN-001"
            assert persisted["editorialStories"][0]["pages"][0]["durationSeconds"] == 15
    finally:
        Path("test_teleprompter.db").unlink(missing_ok=True)
