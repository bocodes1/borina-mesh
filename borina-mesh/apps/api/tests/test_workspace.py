from sqlmodel import Session, create_engine, SQLModel, select

from models import AgentWorkspace


def make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_workspace_entry_model():
    engine = make_engine()
    with Session(engine) as s:
        entry = AgentWorkspace(
            workspace_id="pipeline-001",
            agent_id="scout",
            key="product_lead",
            value='{"name": "Widget X", "score": 8.5}',
        )
        s.add(entry)
        s.commit()
        s.refresh(entry)
        assert entry.id is not None
        assert entry.workspace_id == "pipeline-001"
        assert entry.agent_id == "scout"


def test_workspace_multiple_entries():
    engine = make_engine()
    with Session(engine) as s:
        s.add(AgentWorkspace(workspace_id="p1", agent_id="scout", key="lead", value="{}"))
        s.add(AgentWorkspace(workspace_id="p1", agent_id="researcher", key="validation", value="{}"))
        s.commit()
    with Session(engine) as s:
        entries = s.exec(
            select(AgentWorkspace).where(AgentWorkspace.workspace_id == "p1")
        ).all()
        assert len(entries) == 2
