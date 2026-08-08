function escapeHtml(value: string) {
	return value.replace(/[&<>"']/g, (character) => ({
		"&": "&amp;",
		"<": "&lt;",
		">": "&gt;",
		'"': "&quot;",
		"'": "&#039;",
	})[character] ?? character);
}

function inlineMarkdown(value: string) {
	return escapeHtml(value)
		.replace(/`([^`]+)`/g, "<code>$1</code>")
		.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
		.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function tableCells(value: string) {
	return value.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function isTableSeparator(value: string) {
	const cells = tableCells(value);
	return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function isBlockStart(lines: string[], index: number) {
	const line = lines[index]?.trim() || "";
	if (!line) return true;
	if (/^(#{1,4})\s+/.test(line) || /^```/.test(line) || /^>\s?/.test(line)) return true;
	if (/^[-*]\s+/.test(line) || /^\d+[.)]\s+/.test(line) || /^-{3,}$/.test(line)) return true;
	return line.includes("|") && isTableSeparator(lines[index + 1] || "");
}

/** Render the Markdown subset emitted by the controlled content Agent.
 * Raw HTML is always escaped and links are restricted to http(s).
 */
export function markdownToSafeHtml(markdown: string) {
	const lines = markdown.replaceAll("\r\n", "\n").split("\n");
	const output: string[] = [];
	let index = 0;
	while (index < lines.length) {
		const line = lines[index].trim();
		if (!line) {
			index += 1;
			continue;
		}
		if (line.startsWith("```")) {
			const code: string[] = [];
			index += 1;
			while (index < lines.length && !lines[index].trim().startsWith("```")) {
				code.push(lines[index]);
				index += 1;
			}
			index += index < lines.length ? 1 : 0;
			output.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
			continue;
		}
		if (line.includes("|") && isTableSeparator(lines[index + 1] || "")) {
			const headers = tableCells(line);
			index += 2;
			const rows: string[][] = [];
			while (index < lines.length && lines[index].trim().includes("|") && lines[index].trim()) {
				rows.push(tableCells(lines[index]));
				index += 1;
			}
			output.push(`<div class="markdown-table-wrap"><table><thead><tr>${headers.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((_header, cellIndex) => `<td>${inlineMarkdown(row[cellIndex] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
			continue;
		}
		const heading = line.match(/^(#{1,4})\s+(.+)$/);
		if (heading) {
			const level = Math.min(3, heading[1].length);
			output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
			index += 1;
			continue;
		}
		if (/^[-*]\s+/.test(line)) {
			const items: string[] = [];
			while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
				items.push(lines[index].trim().replace(/^[-*]\s+/, ""));
				index += 1;
			}
			output.push(`<ul>${items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</ul>`);
			continue;
		}
		if (/^\d+[.)]\s+/.test(line)) {
			const items: string[] = [];
			while (index < lines.length && /^\d+[.)]\s+/.test(lines[index].trim())) {
				items.push(lines[index].trim().replace(/^\d+[.)]\s+/, ""));
				index += 1;
			}
			output.push(`<ol>${items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</ol>`);
			continue;
		}
		if (/^>\s?/.test(line)) {
			const quote: string[] = [];
			while (index < lines.length && /^>\s?/.test(lines[index].trim())) {
				quote.push(lines[index].trim().replace(/^>\s?/, ""));
				index += 1;
			}
			output.push(`<blockquote>${inlineMarkdown(quote.join(" "))}</blockquote>`);
			continue;
		}
		if (/^-{3,}$/.test(line)) {
			output.push("<hr>");
			index += 1;
			continue;
		}
		const paragraph = [line];
		index += 1;
		while (index < lines.length && lines[index].trim() && !isBlockStart(lines, index)) {
			paragraph.push(lines[index].trim());
			index += 1;
		}
		output.push(`<p>${paragraph.map(inlineMarkdown).join("<br>")}</p>`);
	}
	return output.join("");
}
