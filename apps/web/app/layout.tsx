import type { Metadata } from "next";
import "./globals.css";
import "./geo-v1-overrides.css";
import "./model-channel-refinement.css";
import "./question-library.css";
import "./question-analysis.css";
import "./question-analysis-selector.css";

export const metadata: Metadata = {
	title: "GEO 优化平台",
	description: "多智能体协同的企业 GEO 优化服务系统",
	icons: {
		icon: "/favicon.ico",
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
