from pathlib import Path

import yaml

from app.v1.agent_orchestration import developer_instructions as content_instructions
from app.v1.opportunity_agent import developer_instructions as opportunity_instructions
from app.v1.website_gap_agent import (
    _developer_instructions as website_instructions,
    load_skill_contract,
)


def test_agent_instructions_use_the_current_workspace_brand() -> None:
    brand_name = "其他租户品牌"
    skill = load_skill_contract()

    prompts = [
        content_instructions(brand_name),
        opportunity_instructions(brand_name),
        website_instructions(skill, brand_name),
    ]

    assert all(brand_name in prompt for prompt in prompts)
    assert all("春秋元泉" not in prompt for prompt in prompts)

    skill_root = Path(__file__).resolve().parents[1] / "app/agent_skills/cqyq-geo-official-site-gap-analysis"
    metadata_text = (skill_root / "agents/openai.yaml").read_text(encoding="utf-8")
    metadata = yaml.safe_load(metadata_text)
    assert "春秋元泉" not in metadata_text
    assert "$cqyq-geo-official-site-gap-analysis" in metadata["interface"]["default_prompt"]
