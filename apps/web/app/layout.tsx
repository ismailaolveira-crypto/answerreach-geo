import type { Metadata } from "next";
import "./globals.css";
import "./geo-v1-overrides.css";
import "./model-channel-refinement.css";
import "./question-library.css";
import "./question-analysis.css";
import "./question-analysis-selector.css";

export const metadata: Metadata = {
	title: "入答 AnswerReach｜企业 GEO 增长工作台",
	description: "让品牌进入 AI 的答案。以真实证据驱动企业 GEO 洞察、行动与效果核验。",
	icons: {
		icon: "/icon.svg",
		shortcut: "/favicon.ico",
	},
};

export default function RootLayout({
	children,
}: Readonly<{ children: React.ReactNode }>) {
	return (
		<html lang="zh-CN">
			<body>{children}</body>
		</html>
	);
}
