from app.services import trace_alerts


def test_trace_alert_dispatcher_commits_background_sync(monkeypatch) -> None:
    state = {"committed": False}

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def commit(self) -> None:
            state["committed"] = True

    def fake_sync(db, current_user, *, days: int, project_id: int | None) -> int:
        assert isinstance(db, FakeSession)
        assert current_user is None
        assert days == trace_alerts.settings.observability_alert_lookback_days
        assert project_id is None
        return 3

    monkeypatch.setattr(trace_alerts, "SessionLocal", FakeSession)
    monkeypatch.setattr(trace_alerts, "sync_trace_alerts", fake_sync)

    assert trace_alerts.TraceAlertDispatcher().sync_once() == 3
    assert state["committed"] is True
