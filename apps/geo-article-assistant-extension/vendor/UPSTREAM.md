# Wechatsync 上游代码说明

- 上游仓库：https://github.com/wechatsync/Wechatsync
- 固定提交：`a98e42865387285afcc027c61836488748f3b30f`
- 本地源码：`vendor/wechatsync-core/src/`
- 许可证：GPL-3.0，见 `vendor/wechatsync-core/LICENSE`

`adapter-bridge.ts` 只导入上游公开的平台适配器，并将调用边界固定为“检测登录态”和“写入草稿”。GEO 文章助手不暴露上游的自动发布入口。

上游 CSDN 适配器包含第三方固定签名凭证，本项目未引入该文件，也未将该凭证打入扩展。CSDN 仅保留平台入口并明确显示“需官方授权”，取得合规的官方授权前不会调用草稿接口。
