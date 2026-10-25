import { Table, TableBody, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";

import type { AdminPromptRouteCell, AdminPromptRoutingResponse, RoutingLane } from "@/entities/prompt-routing";
import { DenseTable } from "@/shared/ui/DenseTable";

import { cellKeyOf, type RoutingFormValues } from "../model/schema";
import { RoutingRow } from "./RoutingRow";

type RoutingLaneTableProps = {
  lane: RoutingLane;
  data: AdminPromptRoutingResponse;
  saved: RoutingFormValues;
};

/** 행 = (단계 × 방), 열 = 속성. 같은 단계의 두 방을 연달아 두어 "이 단계를 방마다 다르게"를 눈으로 비교하게 한다. 단계 순서는
 * 서버 칸 순서(그 레인의 단계 순서)를 따른다. */
export function RoutingLaneTable({ lane, data, saved }: RoutingLaneTableProps) {
  const rows = laneRows(data.cells, lane);

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <DenseTable surface="card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>단계</TableHead>
              <TableHead>방</TableHead>
              <TableHead>부를 모델·경로</TableHead>
              <TableHead>읽을 체인</TableHead>
              <TableHead>지금 운영 값</TableHead>
              <TableHead>단가(USD/1M)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((cell, index) => (
              <RoutingRow
                key={cellKeyOf(cell)}
                cell={cell}
                data={data}
                showsStage={rows[index - 1]?.stage !== cell.stage}
                saved={saved.cells[cellKeyOf(cell)]}
              />
            ))}
          </TableBody>
        </Table>
      </DenseTable>
    </div>
  );
}

export function laneRows(cells: readonly AdminPromptRouteCell[], lane: RoutingLane): AdminPromptRouteCell[] {
  const laneCells = cells.filter((cell) => cell.lane === lane);
  const stages = [...new Set(laneCells.map((cell) => cell.stage))];
  return stages.flatMap((stage) => laneCells.filter((cell) => cell.stage === stage));
}
