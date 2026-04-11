from sqlmodel import Session, create_engine, SQLModel
from models import AgentTask


def make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_agent_task_model():
    engine = make_engine()
    with Session(engine) as s:
        task = AgentTask(title="Scout for trending products", assigned_agent="scout")
        s.add(task)
        s.commit()
        s.refresh(task)
        assert task.id is not None
        assert task.status == "backlog"
        assert task.priority == "medium"


def test_agent_task_status_transitions():
    engine = make_engine()
    with Session(engine) as s:
        task = AgentTask(title="Validate product X", status="in_progress")
        s.add(task)
        s.commit()
        s.refresh(task)
        assert task.status == "in_progress"
        task.status = "done"
        s.add(task)
        s.commit()
        s.refresh(task)
        assert task.status == "done"
