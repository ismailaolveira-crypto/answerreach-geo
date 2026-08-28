from pathlib import Path

from PIL import Image

from app.services.article_media import MAX_ARTICLE_VISUALS, choose_media_strategy, inspect_image
from app.v1.agent_orchestration import OUTPUT_SCHEMA, _prompt


def test_factual_visual_is_forced_to_sourced_web_path() -> None:
    strategy, reason = choose_media_strategy(
        {
            "strategy": "generate",
            "factual_subject": False,
            "purpose": "展示真实产品界面截图和官方 Logo",
        }
    )

    assert strategy == "web_search"
    assert "真实主体" in reason


def test_conceptual_visual_uses_generation_path() -> None:
    strategy, reason = choose_media_strategy(
        {
            "strategy": "generate",
            "factual_subject": False,
            "purpose": "解释企业 GEO 复测闭环",
            "decision_reason": "流程关系适合用定制图解释",
        }
    )

    assert strategy == "generate"
    assert reason == "流程关系适合用定制图解释"


def test_image_inspection_requires_real_publishable_dimensions(tmp_path: Path) -> None:
    image_path = tmp_path / "article.png"
    Image.new("RGB", (1200, 675), "white").save(image_path)

    inspected = inspect_image(image_path)

    assert inspected.media_type == "image/png"
    assert inspected.width == 1200
    assert inspected.height == 675
    assert len(inspected.sha256) == 64


def test_model_decides_visual_count_with_only_a_safety_ceiling() -> None:
    visual_schema = OUTPUT_SCHEMA["properties"]["visual_assets"]
    prompt = _prompt({})

    assert "minItems" not in visual_schema
    assert visual_schema["maxItems"] == MAX_ARTICLE_VISUALS
    assert "do not aim for a fixed count" in prompt
    assert "return an empty visual_assets array" in prompt.lower()
    assert "one or two useful article images" not in prompt


def test_visual_schema_supports_multiple_distinct_section_placements() -> None:
    placement_schema = OUTPUT_SCHEMA["properties"]["visual_assets"]["items"]["properties"][
        "placement"
    ]

    assert "cover" in placement_schema["enum"]
    assert "after_section_6" in placement_schema["enum"]
