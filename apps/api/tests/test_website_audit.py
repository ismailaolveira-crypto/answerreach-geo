from collections.abc import Generator
from datetime import datetime, timezone
from hashlib import sha256
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
from app.models import AuditLog
from app.models.company import Company
from app.models.cleanroom_v1 import (
    GeoActionEvent,
    GeoActionOpportunity,
    GeoAgentRun,
    GeoBrandFact,
    GeoContentAsset,
    GeoContentBrief,
    GeoContentClaim,
    GeoOptimizationAction,
    GeoPlatformVariant,
    GeoWebsiteAudit,
    GeoWorkspace,
)
from app.models.user import User
from app.v1 import routes
from app.v1.agent_orchestration import _build_context
from app.v1.website_audit import (
    BrandFactSourceVerificationError,
    PublicationVerificationError,
    WebsiteAuditTargetError,
    audit_website,
    verify_brand_fact_source,
    verify_publication_page,
)


def public_resolver(_host: str, _port: int) -> list[str]:
    return ["93.184.216.34"]


def test_publication_verification_returns_compact_response_evidence() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><body>" + ("真实公开文章内容" * 20) + "</body></html>",
        )
    )
    with httpx.Client(transport=transport) as client:
        result = verify_publication_page(
            "https://brand.example/article/1",
            resolver=public_resolver,
            client=client,
        )
    assert result["status"] == "publicly_verified"
    assert result["status_code"] == 200
    assert result["content_type"] == "text/html"
    assert result["sha256"]
    assert result["size_bytes"] > 64
    assert "body" not in result


def test_publication_verification_rejects_non_html_response() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"status": "ok", "padding": "x" * 100},
        )
    )
    with httpx.Client(transport=transport) as client:
        with pytest.raises(PublicationVerificationError, match="public_page_not_html"):
            verify_publication_page(
                "https://brand.example/api/article/1",
                resolver=public_resolver,
                client=client,
            )


def test_brand_fact_source_verification_requires_visible_exact_statement() -> None:
    statement = "春秋元泉面向企业提供 Token 统一管控能力。"
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=f"<html><body><main><h1>产品说明</h1><p>{statement}</p></main></body></html>",
        )
    )
    with httpx.Client(transport=transport) as client:
        result = verify_brand_fact_source(
            "https://brand.example/product",
            statement,
            resolver=public_resolver,
            client=client,
        )
        with pytest.raises(
            BrandFactSourceVerificationError,
            match="brand_fact_statement_not_found",
        ):
            verify_brand_fact_source(
                "https://brand.example/product",
                "页面中不存在的产品承诺。",
                resolver=public_resolver,
                client=client,
            )

    assert result["status"] == "source_and_statement_verified"
    assert result["verification_mode"] == "server_rendered_html"
    assert result["evidence_url"] == "https://brand.example/product"
    assert result["statement_sha256"] == sha256(statement.encode("utf-8")).hexdigest()
    assert "body" not in result


def test_brand_fact_source_verification_follows_bounded_same_origin_scripts() -> None:
    statement = "企业 AI 系统的统一 Token 管理与模型调度平台"

    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text='<html><body><div id="app"></div><script type="module" src="/assets/app.js"></script></body></html>',
            )
        if request.url.path == "/assets/app.js":
            return httpx.Response(
                200,
                headers={"content-type": "application/javascript"},
                text='const chunks=["./brand-copy.js"];',
            )
        if request.url.path == "/assets/brand-copy.js":
            return httpx.Response(
                200,
                headers={"content-type": "application/javascript"},
                text=f'export const positioning="{statement}";',
            )
        return httpx.Response(404, headers={"content-type": "text/plain"})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        result = verify_brand_fact_source(
            "https://brand.example/",
            statement,
            resolver=public_resolver,
            client=client,
        )

    assert result["status"] == "source_and_statement_verified"
    assert result["verification_mode"] == "same_origin_public_javascript"
    assert result["verified_url"] == "https://brand.example/"
    assert result["evidence_url"] == "https://brand.example/assets/brand-copy.js"
    assert result["source_sha256"] != result["source_page_sha256"]


def test_brand_fact_source_verification_ignores_cross_origin_scripts() -> None:
    statement = "不应由第三方脚本证明的品牌陈述。"
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                '<html><body><div id="app"></div>'
                f'<script src="https://cdn.example/app.js">{statement}</script></body></html>'
            ),
        )
    )
    with httpx.Client(transport=transport) as client:
        with pytest.raises(
            BrandFactSourceVerificationError,
            match="brand_fact_statement_not_found",
        ):
            verify_brand_fact_source(
                "https://brand.example/",
                statement,
                resolver=public_resolver,
                client=client,
            )


def test_brand_fact_source_verification_rejects_private_targets() -> None:
    with pytest.raises(WebsiteAuditTargetError):
        verify_brand_fact_source(
            "http://localhost:8000/internal",
            "不应读取的内部文本。",
            resolver=lambda _host, _port: ["127.0.0.1"],
        )


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


def test_brand_fact_gate_only_applies_when_server_visible_product_copy_is_missing() -> None:
    readable_opportunity = SimpleNamespace(
        opportunity_type="website_citation_readiness",
        scope_snapshot={"finding_codes": ["meta_description_missing", "canonical_missing"]},
    )
    js_shell_opportunity = SimpleNamespace(
        opportunity_type="website_citation_readiness",
        scope_snapshot={"finding_codes": ["client_rendering_required"]},
    )

    assert routes._website_requires_sourced_brand_facts(readable_opportunity) is False
    assert routes._website_requires_sourced_brand_facts(js_shell_opportunity) is True


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
    monkeypatch.setattr(
        routes,
        "verify_brand_fact_source",
        lambda url, statement: {
            "status": "source_and_statement_verified",
            "verified_url": url,
            "status_code": 200,
            "content_type": "text/html",
            "source_sha256": "a" * 64,
            "statement_sha256": sha256(statement.strip().encode("utf-8")).hexdigest(),
            "size_bytes": 1024,
            "truncated": False,
            "redirect_count": 0,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        },
    )
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
        assert context["website_audit_evidence"]["requires_sourced_brand_facts"] is True
        assert "<div id=\"app\">" in context["website_audit_evidence"]["raw_homepage_html_excerpt"]
        assert set(context["platforms"]) == {"official_site"}


def test_website_draft_requires_active_sourced_brand_fact(
    website_audit_api: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _needs_work_capture()
    captured["checked_at"] = datetime.now(timezone.utc)
    monkeypatch.setattr(routes, "audit_website", lambda _url, *, brand_name: dict(captured))
    monkeypatch.setattr(
        routes,
        "diagnose_local_codex",
        lambda: {
            "runtime_key": "local_codex",
            "sdk_installed": True,
            "sdk_version": "test",
            "runtime_version": "Codex Desktop/test",
            "ready": True,
            "login_status": "chatgpt_authenticated",
            "default_model": "gpt-5-codex",
            "available_models": ["gpt-5-codex"],
            "error": None,
        },
    )
    client: TestClient = website_audit_api.client
    assert client.post("/api/v1/workspaces/1/website-audits").status_code == 201
    opportunity = client.get("/api/v1/workspaces/1/action-opportunities").json()[0]
    action = client.post(
        f"/api/v1/workspaces/1/action-opportunities/{opportunity['id']}/select"
    ).json()

    blocked = client.post(
        f"/api/v1/workspaces/1/actions/{action['id']}/agent-runs",
        json={"selected_platforms": ["official_site"]},
    )
    assert blocked.status_code == 409
    assert "品牌事实" in blocked.json()["detail"]

    invalid_fact = client.post(
        "/api/v1/workspaces/1/brand-facts",
        json={
            "title": "无效来源",
            "statement": "这条记录不应被保存。",
            "source_url": "not-a-public-url",
        },
    )
    assert invalid_fact.status_code == 422
    blank_fact = client.post(
        "/api/v1/workspaces/1/brand-facts",
        json={
            "title": "   ",
            "statement": "不能保存空白名称。",
            "source_url": "https://brand.example/blank",
        },
    )
    assert blank_fact.status_code == 422

    created_fact = client.post(
        "/api/v1/workspaces/1/brand-facts",
        json={
            "title": "产品定位",
            "statement": "春秋元泉面向企业提供 Token 统一管控能力。",
            "source_url": "https://brand.example/product",
        },
    )
    assert created_fact.status_code == 201
    assert created_fact.json()["source_verification"]["status"] == (
        "source_and_statement_verified"
    )
    fact_id = created_fact.json()["id"]
    inactive = client.patch(
        f"/api/v1/workspaces/1/brand-facts/{fact_id}", json={"status": "inactive"}
    )
    assert inactive.status_code == 200
    assert inactive.json()["status"] == "inactive"
    assert client.post(
        f"/api/v1/workspaces/1/actions/{action['id']}/agent-runs",
        json={"selected_platforms": ["official_site"]},
    ).status_code == 409

    active = client.patch(
        f"/api/v1/workspaces/1/brand-facts/{fact_id}", json={"status": "active"}
    )
    assert active.status_code == 200
    queued = client.post(
        f"/api/v1/workspaces/1/actions/{action['id']}/agent-runs",
        json={"selected_platforms": ["official_site"]},
    )
    assert queued.status_code == 202
    assert queued.json()["selected_platforms"] == ["official_site"]

    listed_facts = client.get("/api/v1/workspaces/1/brand-facts")
    assert listed_facts.status_code == 200
    assert listed_facts.json()[0]["source_verification"]["source_sha256"] == "a" * 64
    with website_audit_api.session_factory() as db:
        verification_log = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "workspace.brand_fact.source_verified",
                AuditLog.resource_id == fact_id,
            )
        )
        assert verification_log is not None
        assert verification_log.detail_json["verification"]["source_sha256"] == "a" * 64
        db.add(
            GeoBrandFact(
                workspace_id=1,
                title="未核验事实",
                statement="仅有链接不能证明这段陈述。",
                source_url="https://brand.example/unverified",
                status="active",
            )
        )
        db.commit()
        run = db.get(GeoAgentRun, queued.json()["id"])
        assert run is not None
        context, _brief = _build_context(db, run)
        assert [fact["id"] for fact in context["brand"]["stored_facts"]] == [fact_id]

    with website_audit_api.session_factory() as db:
        brief = GeoContentBrief(
            workspace_id=1,
            action_id=action["id"],
            audience="企业决策者",
            intent="decision",
            asset_type="article",
            required_sections=[],
            brand_fact_ids=[],
            evidence_ids=[],
            source_urls=["https://brand.example/"],
            required_claims=[],
            forbidden_claims=[],
            open_questions=[],
            input_fingerprint="website-review-gate",
            status="ready",
        )
        db.add(brief)
        db.flush()
        asset = GeoContentAsset(
            workspace_id=1,
            brief_id=brief.id,
            version=1,
            title="官网整改框架",
            summary="没有品牌事实的通用框架",
            body_markdown="正文",
            content_fingerprint="website-review-asset",
            status="draft",
        )
        db.add(asset)
        db.flush()
        db.add(
            GeoContentClaim(
                content_asset_id=asset.id,
                claim_key="source-1",
                claim_text="公开规则要求正文可见。",
                support_type="public_source",
                source_url="https://developers.google.com/search/docs/",
                verification_status="source_linked",
                introduced_by_model=True,
            )
        )
        db.add(
            GeoPlatformVariant(
                workspace_id=1,
                content_asset_id=asset.id,
                platform_key="official_site",
                version=1,
                policy_version="test",
                title="官网整改框架",
                summary="没有品牌事实的通用框架",
                body_markdown="正文",
                tags=[],
                image_manifest=[],
                adaptation_contract={},
                content_fingerprint="website-review-variant",
                status="ready",
            )
        )
        run = db.get(GeoAgentRun, queued.json()["id"])
        assert run is not None
        run.status = "awaiting_review"
        run.stage = "awaiting_review"
        run.result_snapshot = {
            "asset_id": asset.id,
            "sourced_brand_fact_count": 0,
        }
        db.commit()
        asset_id = asset.id

    review_blocked = client.post(
        f"/api/v1/workspaces/1/content-assets/{asset_id}/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [],
            "platform_keys": ["official_site"],
            "reviewed_platform_keys": ["official_site"],
            "note": "规则来源已核对",
        },
    )
    assert review_blocked.status_code == 409
    assert "通用整改框架" in review_blocked.json()["detail"]

    blocked_package = client.get(
        f"/api/v1/workspaces/1/content-assets/{asset_id}/review-package"
    ).json()
    assert blocked_package["requires_sourced_brand_facts"] is True
    assert blocked_package["sourced_brand_fact_count"] == 0

    with website_audit_api.session_factory() as db:
        run = db.get(GeoAgentRun, queued.json()["id"])
        assert run is not None
        run.result_snapshot = {
            **(run.result_snapshot or {}),
            "sourced_brand_fact_count": 1,
            "sourced_brand_fact_ids": [fact_id],
        }
        db.commit()

    metadata_only_is_blocked = client.post(
        f"/api/v1/workspaces/1/content-assets/{asset_id}/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [],
            "platform_keys": ["official_site"],
            "reviewed_platform_keys": ["official_site"],
            "note": "仅有运行元数据，不应绕过内容证据门禁",
        },
    )
    assert metadata_only_is_blocked.status_code == 409

    with website_audit_api.session_factory() as db:
        db.add(
            GeoContentClaim(
                content_asset_id=asset_id,
                claim_key="brand-fact-1",
                claim_text="春秋元泉面向企业提供 Token 统一管控能力。",
                support_type="brand_fact",
                support_id=fact_id,
                source_url="https://brand.example/product",
                verification_status="source_linked",
                introduced_by_model=False,
            )
        )
        db.commit()

    ready_package = client.get(
        f"/api/v1/workspaces/1/content-assets/{asset_id}/review-package"
    ).json()
    assert ready_package["sourced_brand_fact_count"] == 1
    assert ready_package["sourced_brand_fact_ids"] == [fact_id]

    approved = client.post(
        f"/api/v1/workspaces/1/content-assets/{asset_id}/reviews",
        json={
            "verdict": "approved",
            "confirmed_claim_ids": [],
            "platform_keys": ["official_site"],
            "reviewed_platform_keys": ["official_site"],
            "note": "规则与品牌事实均已核对",
        },
    )
    assert approved.status_code == 201
    assert approved.json()["approved_platform_keys"] == ["official_site"]
