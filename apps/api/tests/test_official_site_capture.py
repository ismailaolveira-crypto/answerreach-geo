from pathlib import Path

from PIL import Image, ImageDraw

from app.services.official_site_capture import (
    CommandResult,
    OfficialSiteCapture,
    captured_visual_purpose,
)
from app.services.article_media import MAX_ARTICLE_VISUALS


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
        if arguments and arguments[0] == "playwright":
            if not self.playwright_ok:
                return CommandResult(stdout="", stderr="capture failed", returncode=1)
            target = Path(arguments[-1])
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
    outcome = OfficialSiteCapture(runner=runner).capture(
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


def test_capture_archives_png_with_isolated_chrome(tmp_path: Path) -> None:
    runner = FakeRunner()
    outcome = OfficialSiteCapture(runner=runner).capture(
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
    assert runner.commands[0][0:2] == ["playwright", "screenshot"]
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

    outcome = OfficialSiteCapture(runner=runner).capture(
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
    outcome = OfficialSiteCapture(runner=FakeRunner()).capture(
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


def test_capture_falls_back_to_connected_browser_and_closes(tmp_path: Path) -> None:
    runner = FakeRunner(playwright_ok=False)
    outcome = OfficialSiteCapture(runner=runner).capture(
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
    assert outcome.status == "captured"
    assert outcome.items[0].capture_engine == "opencli_browser_bridge"
    assert any("material-profile" in command for command in runner.commands)
    assert any("--tab" in command and "page-1" in command for command in runner.commands)
    assert runner.commands[-1][-1] == "close"


def test_capture_rejects_blank_browser_page(tmp_path: Path) -> None:
    outcome = OfficialSiteCapture(
        runner=FakeRunner(playwright_ok=False, empty_page=True)
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
    assert outcome.status == "failed"
    assert outcome.reason == "official_page_visual_empty"
    assert outcome.items == []
