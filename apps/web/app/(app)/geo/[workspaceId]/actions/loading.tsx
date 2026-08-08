export default function PriorityActionsLoading() {
	return <main className="geo-route-loading" aria-live="polite" aria-busy="true">
		<section>
			<span className="geo-route-loading-mark" aria-hidden="true" />
			<div>
				<b>正在整理真实机会与 Agent 状态</b>
				<p>正在读取当前批次、持久化运行、内容审核与发布进度。</p>
			</div>
		</section>
		<div className="geo-route-loading-grid" aria-hidden="true"><i /><i /><i /><i /></div>
	</main>;
}
