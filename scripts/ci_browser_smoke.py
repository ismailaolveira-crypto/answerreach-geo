"""No-cost browser regression for the local Web/API session boundary.

The script creates an isolated CI tenant through the real registration UI. It
never configures a Provider, starts an observation batch, or contacts an office
platform.
"""

from __future__ import annotations

import os
import re
import secrets

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    base_url = os.getenv("GEO_E2E_BASE_URL", "http://127.0.0.1:39003").rstrip("/")
    identity = secrets.token_hex(8)
    email = f"ci-{identity}@example.com"
    password = f"GEO-ci-{identity}-Safe!"

    with sync_playwright() as playwright:
        executable_path = os.getenv("GEO_E2E_BROWSER_EXECUTABLE")
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable_path or None,
        )
        context = browser.new_context(base_url=base_url, locale="zh-CN")
        page = context.new_page()
        try:
            page.goto("/register", wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name="建立 GEO 观测空间")).to_be_visible()
            page.get_by_label("姓名").fill("CI 验收管理员")
            page.get_by_label("工作邮箱").fill(email)
            page.get_by_label("设置密码", exact=True).fill(password)
            page.get_by_label("确认密码", exact=True).fill(password)
            page.get_by_role("button", name="继续设置工作区").click()
            page.get_by_label("公司名称").fill("CI 隔离测试企业")
            page.get_by_label("品牌名称").fill("CI 隔离品牌")
            page.get_by_role("button", name="创建并进入工作台").click()
            page.wait_for_url("**/geo/*", timeout=30_000)
            workspace_id = page.url.split("/geo/", 1)[1].split("/", 1)[0].split("?", 1)[0]

            page.goto(f"/geo/{workspace_id}?__view=decision", wait_until="domcontentloaded")
            expect(page.get_by_text("看见CI 隔离品牌如何进入企业 AI 的真实采购决策。")).to_be_visible()
            assert "春秋元泉" not in page.locator("body").inner_text()

            page.goto(f"/geo/{workspace_id}/competitors", wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name="竞品对比", exact=True)).to_be_visible()
            assert "春秋元泉" not in page.locator("body").inner_text()

            page.goto(f"/geo/{workspace_id}/collaboration", wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name="协作中心")).to_be_visible()
            page.get_by_role("button", name="通讯录").click()
            expect(page.get_by_text("1 位真实账号")).to_be_visible()
            expect(page.get_by_role("button", name=re.compile("未连接"))).to_have_count(3)

            forged_logout = context.request.post(
                f"{base_url}/api/session/logout",
                headers={
                    "Origin": "https://attacker.example",
                    "Sec-Fetch-Site": "cross-site",
                },
            )
            assert forged_logout.status == 403
            page.reload(wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name="协作中心")).to_be_visible()

            page.goto(f"/geo/{workspace_id}/settings", wait_until="domcontentloaded")
            page.get_by_role("button", name="退出登录").click()
            page.wait_for_url("**/login", timeout=15_000)

            page.get_by_label("邮箱").fill(email)
            page.get_by_label("密码").fill(password)
            page.get_by_role("button", name="进入工作台").click()
            page.wait_for_url("**/geo/*", timeout=30_000)
            expect(page.get_by_role("heading", name="经营驾驶舱")).to_be_visible()
            expect(page.get_by_role("combobox", name="当前工作区")).to_have_value(workspace_id)

            page.goto(f"/geo/{workspace_id}/agent", wait_until="domcontentloaded")
            expect(page.get_by_role("button", name="收起会话")).to_be_visible()
            expect(page.get_by_role("button", name="＋ 新建对话")).to_be_visible()
            page.get_by_role("button", name="收起会话").click()
            expect(page.get_by_role("button", name="展开会话")).to_be_visible()
            expect(page.get_by_role("button", name="＋ 新建对话")).to_be_hidden()
            page.reload(wait_until="domcontentloaded")
            expect(page.get_by_role("button", name="展开会话")).to_be_visible()
            page.get_by_role("button", name="展开会话").click()
            expect(page.get_by_role("button", name="＋ 新建对话")).to_be_visible()
        finally:
            context.close()
            browser.close()

    print("CI browser smoke passed: tenant brand isolation, contacts, CSRF rejection, re-login, and Agent sidebar persistence.")


if __name__ == "__main__":
    main()
