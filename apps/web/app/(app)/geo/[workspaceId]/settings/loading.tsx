export default function WorkspaceSettingsLoading() {
	return <main className="geo-route-loading" aria-live="polite" aria-busy="true">
		<section>
			<span className="geo-route-loading-mark" aria-hidden="true" />
			<div>
				<b>正在核对工作区配置</b>
				<p>正在读取品牌口径、来源事实和本机 Agent 状态；不会显示或改写密钥。</p>
			</div>
		</section>
		<div className="geo-route-loading-grid" aria-hidden="true"><i /><i /><i /></div>
	</main>;
}
