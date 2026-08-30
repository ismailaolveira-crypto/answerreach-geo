from pathlib import Path

from PIL import Image, ImageDraw

from app.services.official_site_capture import (
    CommandResult,
    OfficialSiteCapture,
    captured_visual_purpose,
)
from app.services.secure_official_browser import _install_network_policy
from app.services.article_media import MAX_ARTICLE_VISUALS


def public_resolver(_host: str, _port: int) -> list[str]:
    return ["93.184.216.34"]


class FakeRunner:
    def __init__(self, *, playwright_ok: bool = True, empty_page: bool = False) -> None:
        self.commands: list[list[str]] = []
        self.playwright_ok = playwright_ok
        self.empty_page = empty_page

    @staticmethod
    def _write_valid_png(target: Path) -> None:
        image = Image.new("RGB", (1440, 900), "#f5f8ff")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((80, 80, 1360, 360), fill="#1d5ff2")
        drawing.rectangle((80, 420, 700, 820), fill="#d8e5ff")
        drawing.rectangle((740, 420, 1360, 820), fill="#ffffff")
        image.save(target, format="PNG")

    def __call__(self, arguments: list[str], _timeout: int) -> CommandResult:
        self.commands.append(arguments)
        if arguments[1:3] == ["-m", "app.services.secure_official_browser"]:
            if not self.playwright_ok:
                return CommandResult(stdout="", stderr="capture failed", returncode=1)
            target = Path(arguments[arguments.index("--output") + 1])
            self._write_valid_png(target)
            return CommandResult(stdout="", stderr="", returncode=0)
        if arguments[:3] == ["opencli", "profile", "list"]:
            return CommandResult(
                stdout="Connected Browser Bridge profiles\n  • abc123 material-profile — connected v1.0.20\n",
                stderr="",
                returncode=0,
            )
        if "open" in arguments:
            return CommandResult(
                stdout='{"url":"https://brand.example.com/product?id=1","page":"page-1"}',
                stderr="",
                returncode=0,
            )
        if "eval" in arguments:
            state = (
                {"url": "about:blank", "htmlLength": 39, "textLength": 0, "imageCount": 0}
                if self.empty_page
                else {
                    "url": "https://brand.example.com/product?id=1",
                    "htmlLength": 1200,
                    "textLength": 180,
                    "imageCount": 1,
                }
            )
            import json

            return CommandResult(stdout=json.dumps(state), stderr="", returncode=0)
        if "screenshot" in arguments:
            target = Path(next(value for value in arguments if value.endswith(".png")))
            self._write_valid_png(target)
        return CommandResult(stdout="{}", stderr="", returncode=0)


def test_capture_accepts_only_exact_official_host(tmp_path: Path) -> None:
    runner = FakeRunner()
    outcome = OfficialSiteCapture(runner=runner, resolver=public_resolver).capture(
        run_id=7,
        official_website="https://brand.example.com/",
        candidates=[
            {
                "source_url": "https://evil.example.net/copied-product",
                "alt_text": "伪造页面",
                "purpose": "不应采集",
                "recommended_platforms": ["wechat"],
            }
        ],
        output_directory=tmp_path / "visuals",
    )
    assert outcome.status == "rejected"
    assert outcome.items == []
    assert runner.commands == []


def test_capture_requires_the_exact_official_origin(tmp_path: Path) -> None:
    runner = FakeRunner()
    outcome = OfficialSiteCapture(runner=runner, resolver=public_resolver).capture(
        run_id=7,
        official_website="https://brand.example.com/",
        candidates=[
            {
                "source_url": "http://brand.example.com:443/product",
                "alt_text": "降级页面",
                "purpose": "不应采集",
                "recommended_platforms": ["wechat"],
            }
        ],
        output_directory=tmp_path / "visuals",
    )

    assert outcome.status == "rejected"
    assert outcome.reason == "no_official_domain_candidate"
    assert runner.commands == []


def test_capture_archives_png_with_isolated_chrome(tmp_path: Path) -> None:
    runner = FakeRunner()
    outcome = OfficialSiteCapture(runner=runner, resolver=public_resolver).capture(
        run_id=8,
        official_website="https://brand.example.com/",
        candidates=[
            {
                "source_url": "https://brand.example.com/product?id=1#overview",
                "alt_text": "产品能力页",
                "purpose": "支撑公众号配图审核",
                "recommended_platforms": ["wechat", "zhihu"],
            }
        ],
        output_directory=tmp_path / "visuals",
    )
    assert outcome.status == "captured"
    assert len(outcome.items) == 1
    item = outcome.items[0]
    assert item.path.is_file()
    assert item.source_url == "https://brand.example.com/product?id=1"
    assert item.sha256
    assert item.size_bytes == item.path.stat().st_size
    assert item.capture_engine == "playwright_chrome"
    assert runner.commands[0][1:3] == ["-m", "app.services.secure_official_browser"]
    assert runner.commands[0][runner.commands[0].index("--approved-host") + 1] == (
        "brand.example.com"
    )
    assert runner.commands[0][runner.commands[0].index("--approved-address") + 1] == (
        "93.184.216.34"
    )
    assert not any(command[0] == "opencli" for command in runner.commands)


def test_capture_respects_safety_ceiling_without_forcing_a_target_count(tmp_path: Path) -> None:
    runner = FakeRunner()
    candidates = [
        {
            "source_url": f"https://brand.example.com/product-{index}",
            "alt_text": f"产品能力 {index}",
            "purpose": f"解释第 {index} 个独立能力",
            "recommended_platforms": ["wechat"],
        }
        for index in range(MAX_ARTICLE_VISUALS + 2)
    ]

    outcome = OfficialSiteCapture(runner=runner, resolver=public_resolver).capture(
        run_id=11,
        official_website="https://brand.example.com/",
        candidates=candidates,
        output_directory=tmp_path / "visuals",
    )

    assert outcome.status == "captured"
    assert len(outcome.items) == MAX_ARTICLE_VISUALS


def test_captured_purpose_removes_pre_capture_disclaimer() -> None:
    value = (
        "候选截图用于支撑首段产品定位。"
        "建议截取官网中对应的能力说明区域；本任务未执行截图。"
    )

    assert captured_visual_purpose(value) == "该官网截图用于支撑首段产品定位。"


def test_capture_persists_truthful_post_capture_purpose(tmp_path: Path) -> None:
    outcome = OfficialSiteCapture(
        runner=FakeRunner(), resolver=public_resolver
    ).capture(
        run_id=10,
        official_website="https://brand.example.com/",
        candidates=[
            {
                "source_url": "https://brand.example.com/product",
                "alt_text": "产品能力页",
                "purpose": "建议截取官网产品区域；本任务未执行截图。",
                "recommended_platforms": ["official_site"],
            }
        ],
        output_directory=tmp_path / "visuals",
    )

    assert outcome.items[0].purpose == "已从官网真实采集，供内容审核与配图选择。"


def test_capture_never_falls_back_to_connected_user_browser(tmp_path: Path) -> None:
    runner = FakeRunner(playwright_ok=False)
    outcome = OfficialSiteCapture(runner=runner, resolver=public_resolver).capture(
        run_id=8,
        official_website="https://brand.example.com/",
        candidates=[
            {
                "source_url": "https://brand.example.com/product?id=1",
                "alt_text": "产品能力页",
                "purpose": "支撑公众号配图审核",
                "recommended_platforms": ["wechat", "zhihu"],
            }
        ],
        output_directory=tmp_path / "visuals",
    )
    assert outcome.status == "unavailable"
    assert outcome.reason == "isolated_browser_capture_failed"
    assert outcome.items == []
    assert not any(command[0] == "opencli" for command in runner.commands)


def test_capture_rejects_blank_browser_page(tmp_path: Path) -> None:
    outcome = OfficialSiteCapture(
        runner=FakeRunner(playwright_ok=False, empty_page=True),
        resolver=public_resolver,
    ).capture(
        run_id=9,
        official_website="https://brand.example.com/",
        candidates=[
            {
                "source_url": "https://brand.example.com/product",
                "alt_text": "产品页",
                "purpose": "审核配图",
                "recommended_platforms": ["wechat"],
            }
        ],
        output_directory=tmp_path / "visuals",
    )
    assert outcome.status == "unavailable"
    assert outcome.reason == "isolated_browser_capture_failed"
    assert outcome.items == []


def test_capture_rejects_private_dns_before_starting_browser(tmp_path: Path) -> None:
    runner = FakeRunner()
    outcome = OfficialSiteCapture(
        runner=runner,
        resolver=lambda _host, _port: ["127.0.0.1"],
    ).capture(
        run_id=12,
        official_website="https://brand.example.com/",
        candidates=[
            {
                "source_url": "https://brand.example.com/product",
                "alt_text": "产品页",
                "purpose": "审核配图",
                "recommended_platforms": ["wechat"],
            }
        ],
        output_directory=tmp_path / "visuals",
    )

    assert outcome.status == "rejected"
    assert outcome.reason == "unsafe_official_target"
    assert runner.commands == []


def test_isolated_browser_policy_is_context_wide_and_blocks_websockets() -> None:
    class FakeRequest:
        def __init__(self, url: str) -> None:
            self.url = url

    class FakeRoute:
        def __init__(self, url: str) -> None:
            self.request = FakeRequest(url)
            self.action: str | None = None

        def continue_(self) -> None:
            self.action = "continued"

        def abort(self, _reason: str) -> None:
            self.action = "aborted"

    class FakeSocket:
        def __init__(self) -> None:
            self.closed: tuple[int | None, str | None] | None = None

        def close(self, *, code=None, reason=None) -> None:
            self.closed = (code, reason)

    class FakeContext:
        route_handler = None
        socket_handler = None

        def route(self, pattern, handler) -> None:
            assert pattern == "**/*"
            self.route_handler = handler

        def route_web_socket(self, pattern, handler) -> None:
            assert pattern == "**/*"
            self.socket_handler = handler

    context = FakeContext()
    _install_network_policy(context, host="brand.example.com", port=443, scheme="https")
    assert context.route_handler is not None
    assert context.socket_handler is not None
    allowed = FakeRoute("https://brand.example.com/product")
    blocked_popup = FakeRoute("http://127.0.0.1/admin")
    context.route_handler(allowed)
    context.route_handler(blocked_popup)
    assert allowed.action == "continued"
    assert blocked_popup.action == "aborted"
    socket = FakeSocket()
    context.socket_handler(socket)
    assert socket.closed == (1008, "network policy")
