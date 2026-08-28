import GeoWorkspacePage from "../../page";

type Props = {
	params: Promise<{ workspaceId: string }>;
	searchParams: Promise<Record<string, string | string[] | undefined>>;
};

// The internal flag selects the preserved decision view without exposing a
// second implementation that could drift from the original interface.
export default async function DecisionInsightPage({ params, searchParams }: Props) {
	return GeoWorkspacePage({
		params,
		searchParams: Promise.resolve({ ...(await searchParams), __view: "decision" }),
	});
}

export const maxDuration = 300;
