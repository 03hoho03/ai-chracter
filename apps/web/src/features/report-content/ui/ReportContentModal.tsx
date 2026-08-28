import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { createCallable } from "react-call";
import { useMutationFlow, type MutationFn } from "react-call/mutation-flow";

import type { ReportReasonCategory } from "@/entities/content";

const REPORT_REASON_OPTIONS: { value: ReportReasonCategory; label: string }[] = [
  { value: "adult", label: "성인/선정적 콘텐츠" },
  { value: "copyright", label: "저작권 침해" },
  { value: "hate", label: "혐오·범죄 조장" },
  { value: "spam", label: "스팸" },
  { value: "other", label: "기타" },
];

/** Radix 단일선택 토글은 선택된 항목을 다시 누르면 빈 문자열을 흘려보내고 `ToggleGroupItem`의 value도
 * `string`이라, 화면에서 돌아오는 값에는 좁힘이 필요하다. `as` 단언 대신 술어를 쓴다(TS-03).
 * 화면이 실제로 그리는 목록을 근거로 삼으므로 옵션과 술어가 어긋날 수 없다. */
function isReportReason(value: string): value is ReportReasonCategory {
  return REPORT_REASON_OPTIONS.some((option) => option.value === value);
}

type Props = {
  mutationFn: MutationFn<void, ReportReasonCategory>;
};

/** techspec-content-detail.md §5, techspec-overview.md §9 — 이 프로젝트 첫 react-call 액션형 모달.
 * 실제 신고 API 호출/토스트/성공 판단은 호출부가 넘기는 mutationFn이 담당하고, 이 컴포넌트는
 * 사유 단일 선택 UI + 제출 상태 표시만 책임진다. */
export const ReportContentModal = createCallable<Props, void>(({ call, mutationFn }) => {
  const [reason, setReason] = useState<ReportReasonCategory>();
  const submit = useMutationFlow(call, mutationFn);

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>신고하기</DialogTitle>
          <DialogDescription>신고 사유를 선택해주세요.</DialogDescription>
        </DialogHeader>

        <ToggleGroup
          type="single"
          variant="list"
          orientation="vertical"
          value={reason ?? ""}
          onValueChange={(value) => setReason(isReportReason(value) ? value : undefined)}
          aria-label="신고 사유 선택"
          className="w-full"
        >
          {REPORT_REASON_OPTIONS.map((option) => (
            <ToggleGroupItem key={option.value} value={option.value} className="h-11 w-full justify-start px-3">
              {option.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>

        <DialogFooter>
          <Button
            className="w-full"
            disabled={!reason || submit.pending}
            onClick={() => reason && submit(reason)}
          >
            {submit.pending ? "접수 중..." : "신고하기"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
