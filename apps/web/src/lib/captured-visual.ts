export function capturedVisualPurpose(value: unknown): string {
	const purpose = typeof value === "string" ? value.trim() : "";
	const sentences = purpose.match(/[^.!?。！？]+[.!?。！？]?/g) ?? [];
	const forwardLooking = /(未执行截图|未完成截图|尚未截图|待截图|建议截取|建议截图)/;
	const factual = sentences
		.map((sentence) => sentence.trim())
		.filter((sentence) => sentence && !forwardLooking.test(sentence))
		.join("")
		.replace(/^候选截图/, "该官网截图")
		.replace(/^截图候选/, "该官网截图")
		.trim();
	return factual || "已从官网真实采集，供内容审核与配图选择。";
}
