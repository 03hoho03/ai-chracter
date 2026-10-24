import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Label } from "@ai-character-chat/ui/components/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import {
  ROOM_MODEL_LABELS,
  ROUTING_LANE_LABELS,
  ROUTING_STAGE_LABELS,
  type AdminPromptRouteCall,
  type AdminPromptRouteCell,
  type AdminPromptRouteRow,
  type AdminPromptRoutingResponse,
} from "@/entities/prompt-routing";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { useSaveRoutingMutation } from "../api/useSaveRoutingMutation";
import { candidateCalls, describeCellForm, formatCachePrice, formatPrice } from "../model/describe";
import type { RoutingOutcome } from "../model/outcome";
import { cellKeyMap, type RouteCellForm } from "../model/schema";
import { classifyRouteSaveError } from "../model/routeErrors";

export type RoutingChange = {
  cell: AdminPromptRouteCell;
  before: RouteCellForm;
  after: RouteCellForm;
};

type SaveRoutingDialogProps = {
  data: AdminPromptRoutingResponse;
  changes: RoutingChange[];
  rows: AdminPromptRouteRow[];
  /** 저장할 행 중 판정 칸에서 읽을 체인과 부를 모델이 다른 칸 수. */
  mismatchCount: number;
};

type SaveFormValues = { note: string };

/** 저장은 커밋 직후 캐시를 지워 다음 턴부터 운영 경로를 바꾸는 되돌리기 어려운 행동이라(프롬프트 게시와 같은 무게) 바뀌는 칸과
 * 단가를 한 번에 보고 메모를 남기게 한다. 기준 이력은 모달을 연 시점에 화면이 보던 표의 이력이다. */
export const SaveRoutingDialog = createCallable<SaveRoutingDialogProps, RoutingOutcome | undefined>(
  ({ call, data, changes, rows, mismatchCount }) => {
    const saveMutation = useSaveRoutingMutation();
    const {
      register,
      handleSubmit,
      formState: { isSubmitting },
    } = useForm<SaveFormValues>({ defaultValues: { note: "" } });
    const nextNumber = (data.revisionNumber ?? 0) + 1;

    const onSubmit = async (values: SaveFormValues) => {
      try {
        const saved = await saveMutation.mutateAsync({ baseRevisionId: data.revisionId, note: values.note, rows });
        call.end({ status: "saved", data: saved });
      } catch (error) {
        const failure = classifyRouteSaveError(error, cellKeyMap(data));
        if (failure.kind === "other") {
          toast.error("저장에 실패했어요. 잠시 후 다시 시도해주세요.");
          return;
        }
        call.end({ status: "failed", failure });
      }
    };

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end(undefined)}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>모델 배정 저장</DialogTitle>
            <DialogDescription>
              r{nextNumber} 이력으로 저장해요. 다음 턴부터 바로 반영돼요. 바뀌는 칸 {changes.length}개:
            </DialogDescription>
          </DialogHeader>
          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              void handleSubmit(onSubmit)(event);
            }}
            className="flex min-h-0 flex-1 flex-col gap-4"
          >
            <DialogBody scrollLabel="바뀐 칸" className="flex flex-col gap-4">
              {mismatchCount > 0 && (
                <p className="break-keep text-sm text-foreground">
                  {mismatchCount}칸은 읽을 체인과 부를 모델이 달라요 — 그 체인 문안은 다른 모델에 맞춰 썼을 수 있어요.
                </p>
              )}
              <div className="shrink-0 overflow-hidden rounded-lg border border-border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>칸</TableHead>
                      <TableHead>지금</TableHead>
                      <TableHead>바꿀 값</TableHead>
                      <TableHead>단가(USD/1M) 지금 → 바꿀 값</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {changes.map(({ cell, before, after }) => (
                      <TableRow key={`${cell.lane}|${cell.roomModel}|${cell.stage}`} className="align-top">
                        <TableCell className="whitespace-normal">
                          {ROUTING_LANE_LABELS[cell.lane]} · {ROOM_MODEL_LABELS[cell.roomModel]} ·{" "}
                          {ROUTING_STAGE_LABELS[cell.stage]}
                        </TableCell>
                        <TableCell className="whitespace-normal text-muted-foreground">
                          {describeCellForm(cell, before, data)}
                        </TableCell>
                        <TableCell className="whitespace-normal text-foreground">
                          {describeCellForm(cell, after, data)}
                        </TableCell>
                        <TableCell className="whitespace-normal tabular-nums">
                          <PriceChange
                            now={cell.calls[0]}
                            next={after.mode === "row" ? candidateCalls(cell, after.pair)?.[0] : undefined}
                          />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <p className="break-keep text-xs text-muted-foreground">
                단가 기준일 {data.pricesAsOf}. 행을 지워 env 기본값으로 돌리는 칸의 단가는 저장 뒤 표에서 확인해요. Claude 직결
                행은 그 단계의 env 판정 모델이 Claude 인 동안에만 저장돼요.
              </p>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="prompt-routing-save-note">메모</Label>
                <Textarea
                  id="prompt-routing-save-note"
                  placeholder="왜 바꿨는지 남겨두면 나중에 되돌릴 때 도움이 돼요."
                  {...register("note")}
                />
              </div>
            </DialogBody>
            <DialogFooter>
              <Button type="button" variant="outline" autoFocus onClick={() => call.end(undefined)}>
                취소
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "저장 중..." : "저장"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);

function PriceChange({ now, next }: { now: AdminPromptRouteCall | undefined; next: AdminPromptRouteCall | undefined }) {
  return (
    <div className="flex flex-col gap-1">
      <CallPrice call={now} />
      <span className="text-muted-foreground">
        → {next === undefined ? <span>env 기본값(저장 뒤 확인)</span> : <CallPrice call={next} />}
      </span>
    </div>
  );
}

function CallPrice({ call }: { call: AdminPromptRouteCall | undefined }) {
  if (call === undefined) return <span className="text-muted-foreground">-</span>;
  return (
    <span className="inline-flex flex-col">
      <span className="text-foreground">{call.modelId}</span>
      {call.price === null ? (
        <span className="text-muted-foreground">단가 표에 없음</span>
      ) : (
        <>
          <span>{formatPrice(call.price)}</span>
          <span className="text-xs text-muted-foreground">{formatCachePrice(call.price)}</span>
        </>
      )}
    </span>
  );
}
