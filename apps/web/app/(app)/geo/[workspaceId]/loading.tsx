export default function GeoWorkspaceLoading() {
	return <main className="geo-route-loading" aria-live="polite" aria-busy="true">
		<section>
			<span className="geo-route-loading-mark" aria-hidden="true" />
			<div>
				<b>正在读取已归档的真实数据</b>
				<p>计算完成后一次呈现，不使用虚假进度。</p>
			</div>
		</section>
		<div className="geo-route-loading-grid" aria-hidden="true"><i /><i /><i /><i /></div>
	</main>;
}
