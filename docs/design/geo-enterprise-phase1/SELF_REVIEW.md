# Phase 1 image2 设计自审

范围：**仅侧边栏**的六个父级分组与洞察四个独立子页
需求：R2、R3、R10、R11
当前结论：**v4 和移动 v2 因越界重做原页面而退回。v5 只设计侧边栏，四个原页面明确保持不变，已通过内部设计自审并完成实现；用户于 2026-08-24 明确回复“侧边栏通过”，Phase 1A 已获得人工验收。Phase 1B 全局范围栏仍需独立 image2 设计、内部自审和用户确认。**

## 版本记录

| 版本 | 文件 | 结论 | 原因 |
|---|---|---|---|
| v1 | `phase1-ia-global-scope-v1.png` | 退回 | 范围筛选和范围摘要被拆成两层，不像一个全局范围；模型标志未对应当前产品。 |
| v2 | `phase1-ia-global-scope-v2.png` | 退回 | 已合并为一条范围栏，但筛选只有 2 个批次，摘要却显示 3 个批次，口径自相矛盾。 |
| v3 | `phase1-ia-global-scope-v3-self-review-passed.png` | 方向被替代 | 数据范围正确，但洞察四页使用内容区横向页签，不符合新的侧边层级要求。 |
| 移动 v1 | `phase1-mobile-ia-global-scope-v1-self-review-passed.png` | 方向被替代 | 移动导航结构可用，但洞察仍使用页内横向页签。 |
| v4 | `phase1-ia-insight-hierarchy-v4-self-review-passed.png` | 退回 | 侧边层级正确，但越界重做了信源页的指标、排行和详情板。 |
| 移动 v2 | `phase1-mobile-insight-hierarchy-v2-self-review-passed.png` | 退回 | 侧边层级正确，但越界重做了移动信源页内容。 |
| v5 | `phase1-sidebar-only-insight-hierarchy-v5-self-review-passed.png` | 内部通过 | 只展示桌面侧边栏和移动导航面板；洞察展开四个独立子页，原页面仅作模糊背景并明示“保持不变”。 |

## Apple Design 自审

| 项目 | 结果 | 证据/实现约束 |
|---|---|---|
| Purpose | 通过 | 本稿只回答“洞察的四个独立页面如何在侧边栏表达”，不解答、改写或装饰原页面。 |
| Simplicity | 通过 | 一级导航收敛为 6 个父级分组；洞察四个子页只在侧边分组中出现一次，内容区不再重复。 |
| Understanding | 通过 | 父级行有展开箭头，子页行有跳转箭头，当前子页同时使用蓝色文字和细指示条。 |
| Familiarity | 通过 | 采用企业产品常见的“父级分组展开子页”，保留品牌、工作区切换和左侧导航心智。 |
| Materials/depth | 通过 | 只在侧边栏/移动导航面板与选中父级使用轻量材质，不触及原页面卡片。 |
| Typography/contrast | 通过 | 系统字体、深藏青正文、蓝色仅用于选中和可操作点，无大面积灰色失效感。 |
| Spatial consistency | 通过 | 洞察父级与四个子页始终在侧边栏原位展开；移动导航面板使用相同顺序和选中逻辑。 |
| Response | 待实现验证 | 按钮和筛选在 pointer-down 立即显示反馈，不用人工延迟。 |
| Interruptibility | 待实现验证 | 弹层开合动效可中断，从当前显示值继续，不锁住输入。 |
| Accessibility | 待实现验证 | 点击目标至少 44×44，支持键盘、焦点、读屏、减少动效/透明度和增加对比度。 |
| Responsive layout | 通过 | v5 在同一稿中分别定义桌面侧边栏和移动导航面板，不改造页面本身。 |

## 范围、数据与品牌约束

- 四个原页面的 TSX、CSS、数据函数和文案不属于本设计稿实施范围。
- v4/移动 v2 生成的新页面数据、指标和布局全部作废。

- 设计稿中的模型图形只表达尺寸、数量和排布，不作为生产素材。
- 正式实现必须直接复用已有 `BrandLogo` 与以下来源登记的官方素材：
  - `apps/web/public/brand/deepseek.svg`
  - `apps/web/public/brand/doubao.png`
  - `apps/web/public/brand/qwen.png`
  - `apps/web/public/brand/glm.svg`
  - `apps/web/public/brand/SOURCES.md`
- 选中的批次、模型和问题数必须由同一个范围对象实时派生，不能分别硬编码。

## 开发前门禁

- [x] 桌面主状态 image2 已生成并通过内部自审。
- [x] 用户确认桌面主要方向。
- [x] 移动端关键布局 image2 生成并通过内部自审。
- [x] 用户确认移动端主要方向。
- [x] 开始修改 Phase 1A 侧边栏产品代码。
- [x] 用户于 2026-08-24 明确回复“侧边栏通过”。

## 选中稿件哈希

`phase1-sidebar-only-insight-hierarchy-v5-self-review-passed.png`
SHA-256: `f862fc0e1017a40470a69cd374fbabc83b4ac2c61792715ae7093a05012283d9`
