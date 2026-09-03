from app.v1.agent_orchestration import developer_instructions as content_instructions
from app.v1.opportunity_agent import developer_instructions as opportunity_instructions
from app.v1.website_gap_agent import _developer_instructions as website_instructions


def test_agent_instructions_use_the_current_workspace_brand() -> None:
    brand_name = "其他租户品牌"
    skill = {"name": "test-skill", "sha256": "0" * 64, "documents": []}

    prompts = [
        content_instructions(brand_name),
        opportunity_instructions(brand_name),
        website_instructions(skill, brand_name),
    ]

    assert all(brand_name in prompt for prompt in prompts)
    assert all("春秋元泉" not in prompt for prompt in prompts)
