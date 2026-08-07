from collections.abc import Generator
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import create_app
from app.models.company import Company
from app.models.cleanroom_v1 import (
    GeoActionEvent,
    GeoActionOpportunity,
    GeoAgentRun,
    GeoOptimizationAction,
    GeoWebsiteAudit,
    GeoWorkspace,
)
from app.models.user import User
from app.v1 import routes
from app.v1.agent_orchestration import _build_context
from app.v1.website_audit import WebsiteAuditTargetError, audit_website


def public_resolver(_host: str, _port: int) -> list[str]:
    return ["93.184.216.34"]


def _transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /\nSitemap: https://brand.example/sitemap.xml")
    if request.url.path == "/sitemap.xml":
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            text="<?xml version='1.0'?><urlset><url><loc>https://brand.example/</loc></url></urlset>",
        )
    return httpx.Response(
        200,
        headers={"content-type": "text/html; charset=utf-8", "etag": '"home-v1"'},
        text="""<!doctype html><html><head>
        <title>春秋元泉 Token 统一管控</title>
        <meta name="description" content="面向企业的 Token 统一管控与私有化说明。">
        <link rel="canonical" href="https://brand.example/">
        <script type="application/ld+json">{"@type":"SoftwareApplication","name":"春秋元泉"}</script>
        </head><body><main><h1>春秋元泉 Token 统一管控平台</h1>
        <p>春秋元泉面向企业提供 Token 统一管控、访问审批和私有化部署能力说明。本文给出适用范围、部署边界、选型标准、验证步骤和可追溯来源，帮助技术团队核对真实能力。</p>
        <h2>适用范围</h2><p>企业可结合已有身份系统、网络边界与审计要求评估适配性。</p>
        <a href="https://www.rfc-editor.org/rfc/rfc6749">查看公开标准</a></main></body></html>""",
    )


def _needs_work_capture() -> dict:
    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/robots.txt", "/sitemap.xml"}:
            return httpx.Response(404, text="not found")
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                '<!doctype html><html><head><title>春秋元泉</title>'
                '<script type="module" src="./assets/index.js"></script></head>'
                '<body><div id="app"></div></body></html>'
            ),
        )

    return audit_website(
        "https://brand.example/",
        brand_name="春秋元泉",
        transport=httpx.MockTransport(transport),
        resolver=public_resolver,
    )


def test_audit_captures_public_artifacts_and_scores_server_visible_content() -> None:
    result = audit_website(
        "https://brand.example/",
        brand_name="春秋元泉",
        transport=httpx.MockTransport(_transport),
        resolver=public_resolver,
    )

    assert result["status"] == "ready"
    assert result["score"] >= 75
    assert result["checks"]["server_visible_content"]["passed"] is True
    assert result["checks"]["structured_data"]["detail"] == "SoftwareApplication"
    assert result["raw_html_sha256"]
    assert {item["kind"] for item in result["artifact_manifest"]} == {
        "homepage",
        "robots",
        "sitemap",
    }
    assert result["discovery_documents"]["robots"]["body"].startswith("User-agent")


def test_audit_does_not_treat_javascript_shell_as_readable_product_content() -> None:
    def js_shell_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/robots.txt", "/sitemap.xml"}:
            return httpx.Response(404, text="not found")
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                '<!doctype html><html><head><title>春秋元泉</title>'
                '<script type="module" src="./assets/index.js"></script></head>'
                '<body><div id="app"></div></body></html>'
            ),
        )

    result = audit_website(
        "https://brand.example/",
        brand_name="春秋元泉",
        transport=httpx.MockTransport(js_shell_transport),
        resolver=public_resolver,
    )

    assert result["status"] == "needs_work"
    assert result["checks"]["accessible"]["passed"] is True
    assert result["checks"]["server_visible_content"]["passed"] is False
    assert "client_rendering_required" in {item["code"] for item in result["findings"]}


def test_audit_blocks_private_network_targets_before_request() -> None:
    with pytest.raises(WebsiteAuditTargetError, match="private_network"):
        audit_website(
            "http://localhost/",
            brand_name="测试品牌",
            transport=httpx.MockTransport(_transport),
            resolver=lambda _host, _port: ["127.0.0.1"],
        )


@pytest.fixture
def website_audit_api(monkeypatch: pytest.MonkeyPatch) -> Generator[SimpleNamespace, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        db.add(Company(id=1, name="测试公司"))
        db.add(User(id=1, company_id=1, name="审核员", email="audit@example.com", role="company_admin"))
        db.add(
            GeoWorkspace(
                id=1,
                company_id=1,
                slug="website-audit",
                brand_name="春秋元泉",
                brand_aliases=[],
                website_url="https://brand.example/",
            )
        )
        db.commit()

    captured = audit_website(
        "https://brand.example/",
        brand_name="春秋元泉",
        transport=httpx.MockTransport(_transport),
        resolver=public_resolver,
    )
    captured["checked_at"] = datetime.now(timezone.utc)
    monkeypatch.setattr(routes, "audit_website", lambda _url, *, brand_name: dict(captured))
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, company_id=1, role="company_admin"
    )
    client = TestClient(app)
    yield SimpleNamespace(client=client, session_factory=session_factory)
    client.close()
    app.dependency_overrides.clear()


def test_api_persists_snapshot_but_never_returns_raw_documents(website_audit_api: SimpleNamespace) -> None:
    client: TestClient = website_audit_api.client
    empty = client.get("/api/v1/workspaces/1/website-audits/latest")
    assert empty.status_code == 200
    assert empty.json() == {"website_url": "https://brand.example/", "latest": None}

    created = client.post("/api/v1/workspaces/1/website-audits")
    assert created.status_code == 201
    payload = created.json()
    assert payload["status"] == "ready"
    assert payload["raw_html_sha256"]
    assert "raw_html" not in payload
    assert "discovery_documents" not in payload

    latest = client.get("/api/v1/workspaces/1/website-audits/latest")
    assert latest.status_code == 200
    assert latest.json()["latest"]["id"] == payload["id"]

    with website_audit_api.session_factory() as db:
        row = db.scalar(select(GeoWebsiteAudit))
        assert row is not None
        assert row.raw_html and "Token 统一管控" in row.raw_html
        assert row.discovery_documents["sitemap"]["sha256"]
        event = db.scalar(select(GeoActionEvent))
        assert event is not None
        assert event.detail["website_audit_id"] == row.id
        assert db.scalar(select(GeoActionOpportunity)) is None


def test_needs_work_audit_becomes_deduplicated_selectable_website_action(
    website_audit_api: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _needs_work_capture()
    captured["checked_at"] = datetime.now(timezone.utc)
    monkeypatch.setattr(routes, "audit_website", lambda _url, *, brand_name: dict(captured))
    client: TestClient = website_audit_api.client

    first = client.post("/api/v1/workspaces/1/website-audits")
    second = client.post("/api/v1/workspaces/1/website-audits")
    assert first.status_code == 201
    assert second.status_code == 201

    listed = client.get("/api/v1/workspaces/1/action-opportunities?batch_id=999")
    assert listed.status_code == 200
    opportunities = listed.json()
    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity["opportunity_type"] == "website_citation_readiness"
    assert opportunity["recommended_platforms"] == ["official_site"]
    assert opportunity["evidence"] == []
    assert opportunity["scope_snapshot"]["source_type"] == "website_audit"
    assert opportunity["scope_snapshot"]["website_audit_id"] == second.json()["id"]
    assert opportunity["scope_snapshot"]["raw_html_sha256"]
    assert client.get(
        "/api/v1/workspaces/1/action-opportunities?model_key=deepseek"
    ).json() == []
    assert client.get(
        "/api/v1/workspaces/1/action-opportunities?question_plan_id=1"
    ).json() == []

    selected = client.post(
        f"/api/v1/workspaces/1/action-opportunities/{opportunity['id']}/select"
    )
    assert selected.status_code == 201
    action = selected.json()
    assert action["question_plan_id"] is None
    assert action["source_evidence_id"] is None
    assert action["selected_scope"]["source_type"] == "website_audit"
    assert action["selected_scope"]["website_audit_id"] == second.json()["id"]

    with website_audit_api.session_factory() as db:
        assert db.scalar(select(GeoActionOpportunity).where(GeoActionOpportunity.status == "selected"))
        action_row = db.scalar(select(GeoOptimizationAction))
        assert action_row is not None
        run = GeoAgentRun(
            workspace_id=1,
            action_id=action_row.id,
            runtime_key="local_codex",
            status="queued",
            stage="queued",
            selected_platforms=["official_site"],
            request_snapshot={},
            result_snapshot={},
        )
        db.add(run)
        db.flush()
        context, brief = _build_context(db, run)
        assert brief.status == "ready"
        assert brief.evidence_ids == []
        assert context["action"]["source_type"] == "website_audit"
        assert context["website_audit_evidence"]["raw_html_sha256"]
        assert "<div id=\"app\">" in context["website_audit_evidence"]["raw_homepage_html_excerpt"]
        assert set(context["platforms"]) == {"official_site"}
