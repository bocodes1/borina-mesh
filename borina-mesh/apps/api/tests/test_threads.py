import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, SQLModel, select

from models import ChatMessage


def make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_chat_message_model():
    engine = make_engine()
    with Session(engine) as s:
        msg = ChatMessage(agent_id="ceo", role="user", content="hello")
        s.add(msg)
        s.commit()
        s.refresh(msg)
        assert msg.id is not None
        assert msg.role == "user"


def test_chat_message_roundtrip():
    engine = make_engine()
    with Session(engine) as s:
        s.add(ChatMessage(agent_id="ceo", role="user", content="what's up"))
        s.add(ChatMessage(agent_id="ceo", role="assistant", content="all good"))
        s.add(ChatMessage(agent_id="trader", role="user", content="status"))
        s.commit()

    with Session(engine) as s:
        ceo_msgs = s.exec(
            select(ChatMessage)
            .where(ChatMessage.agent_id == "ceo")
            .order_by(ChatMessage.created_at)
        ).all()
        assert len(ceo_msgs) == 2
        assert ceo_msgs[0].role == "user"
        assert ceo_msgs[1].role == "assistant"


@pytest.fixture
def client():
    os.environ["DATABASE_URL"] = "sqlite://"

    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)

    from db import get_session
    def override_session():
        with Session(test_engine) as session:
            yield session

    from main import app
    app.dependency_overrides[get_session] = override_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_thread_empty(client):
    resp = client.get("/threads/ceo")
    assert resp.status_code == 200
    assert resp.json() == []


def test_delete_thread(client):
    resp = client.delete("/threads/ceo")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0
