import { NextResponse } from "next/server";
import { getOfficialProviderObservationBatch } from "@/lib/cleanroom-v1-api";

export async function GET(
  _request: Request,
  context: { params: Promise<{ workspaceId: string; batchId: string }> },
) {
  const { workspaceId, batchId } = await context.params;
  try {
    const batch = await getOfficialProviderObservationBatch(workspaceId, Number(batchId));
    return NextResponse.json(batch, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "批次状态暂时不可用" },
      { status: 502 },
    );
  }
}
