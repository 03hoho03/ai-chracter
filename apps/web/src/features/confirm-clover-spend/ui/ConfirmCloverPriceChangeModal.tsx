import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";

import { CloverBalance } from "@/entities/clover";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { cloverPriceChangeCopy } from "../model/confirmCloverPriceChangeCopy";
import type { CloverSpendSurface } from "../model/confirmCloverSpendCopy";

/** 보내는 사이 클로버 가격이 바뀌어 서버가 깎기 전에 멈췄을 때, 새 가격으로 다시 보낼지 묻는다. 하루 한 번 확인
 * (`ConfirmCloverSpendModal`)과 같은 모양·같은 자리다 — 둘 다 클로버가 빠지기 전 사용자의 동의를 받는 절차라 표면을 맞춘다.
 * 확인 뒤 동작이 표면마다 달라 `Promise<boolean>` 만 돌려준다.
 *
 * 잔액을 함께 보이는 이유도 같다 — 새 가격이 오른 쪽이면 "남는가"가 고를 근거다. `bg-muted` 를 쓰지 않는다(모달 표면
 * `popover` 와 값이 같아 사라진다). */
export const ConfirmCloverPriceChangeModal = createCallable<
  { balance: number | undefined; cost: number | undefined; surface: CloverSpendSurface },
  boolean
>(({ call, balance, cost, surface }) => {
  const { description, confirmLabel } = cloverPriceChangeCopy(surface, cost);
  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>클로버 가격이 바뀌었어요</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        {/* 잔액을 못 받았으면 줄을 빼고 묻는다 — 0 으로 지어 보이면 거짓이다. */}
        {balance !== undefined && (
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <span>남은 클로버</span>
            <CloverBalance balance={balance} />
          </p>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end(false)}>
            그만두기
          </Button>
          <Button type="button" onClick={() => call.end(true)}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
