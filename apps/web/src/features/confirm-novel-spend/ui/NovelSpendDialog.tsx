import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import type { ReactNode } from "react";

import { CloverSpendSummary, useCloverBalanceQuery } from "@/entities/clover";

type NovelSpendDialogProps = {
  isOpen: boolean;
  title: string;
  description: string;
  cost: number;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
  /** 금액 줄 위에 놓일 선택(장 모델). 없으면 금액 확인만 있다. */
  children?: ReactNode;
};

/** 소설 작업의 금액 확인 다이얼로그 껍데기 — 두 확인 모달(`ConfirmNovelSpendModal`·`ConfirmChapterSpendModal`)이
 * 같은 모양을 쓰도록 한 벌로 둔다. 잔액은 여기서 직접 읽는다 — 호출부가 미리 받아 넘기면 열 때마다 같은 조회를
 * 되풀이한다. 못 받았으면 금액만 보이고 동의는 막지 않는다(정확한 판정은 서버가 차감 전에 한다).
 *
 * 버튼 순서는 `취소` 먼저다(DOM·시각·탭 셋이 같다, 푸터 프리미티브가 강제). `bg-muted` 를 쓰지 않는다 — 모달
 * 표면(`popover`)과 값이 같아 사라진다. */
export function NovelSpendDialog({
  isOpen,
  title,
  description,
  cost,
  confirmLabel,
  onCancel,
  onConfirm,
  children,
}: NovelSpendDialogProps) {
  const { data: clover } = useCloverBalanceQuery();

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="break-keep">{title}</DialogTitle>
          <DialogDescription className="break-keep">{description}</DialogDescription>
        </DialogHeader>

        {children}
        <CloverSpendSummary cost={cost} balance={clover?.balance} />

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel}>
            취소
          </Button>
          <Button type="button" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
