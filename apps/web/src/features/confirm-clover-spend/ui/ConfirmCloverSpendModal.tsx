import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { createCallable } from "react-call";

import { CloverBalance } from "@/entities/clover";

import { formatCloverSpendConfirmDescription } from "../model/confirmCloverSpendCopy";
import type { CloverSpendSurface } from "../model/confirmCloverSpendCopy";

/** clover-techspec.md CT-13 (clover-goal-prompt.md CL-19) — 무료 한도를 다 쓴 첫 시점에 하루 한 번
 * 묻는다. 확정 뒤 동작이 전송·재생성·편집·미리보기·이미지마다 달라 `Promise<boolean>`만 돌려주고
 * 호출부가 이어받는다(`apps/web/CLAUDE.md`의 기준: *"후속 동작이 호출부마다 다르면 주입형, 같으면
 * 자체 호출형"* — 여기는 다르다). 선례는 `ConfirmStartingSetupChangeModal`.
 *
 * ⚠️ impeccable product 레지스터는 *"Modal as first thought. Modals are usually laziness"* 라고
 * 적는다. 여기서 모달을 쓰는 것은 게으름이 아니라 **CL-19가 정한 동의 절차**다 — 돈이 오가는
 * 첫 차감을 사용자가 모르는 사이에 하지 않겠다는 결정이고, 인라인 배너로는 "동의했다"를 서버에
 * 기록할 지점이 생기지 않는다. 대신 **하루 한 번**으로 묶어 매 턴 흐름을 끊지 않는다.
 *
 * 🔴 `bg-muted`를 쓰지 않는다 — 모달 표면이 `popover`라 값이 같아 1.0000:1로 사라진다
 * (DESIGN.md §5 Status badges). 잔량은 `CloverBalance`의 무채색 잉크 그대로 둔다. */
export const ConfirmCloverSpendModal = createCallable<
  { balance: number; cost: number; surface: CloverSpendSurface },
  boolean
>(
  ({ call, balance, cost, surface }) => {
    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>지금부터 클로버를 써요</DialogTitle>
            {/* 🔴 문구를 여기 적지 않는다 — 채팅은 자정에 열리지만 이미지는 시간당 충전이라
                한 문장을 공유하면 이미지에서 거짓이 된다(`model/confirmCloverSpendCopy.ts`). */}
            <DialogDescription>{formatCloverSpendConfirmDescription(surface, cost)}</DialogDescription>
          </DialogHeader>

          {/* 남은 잔액을 확정 전에 한 번 보여준다 — 동의의 대상이 "얼마가 빠지는가"만이 아니라
              "얼마가 남았는가"이기도 하다. 표시 어휘는 다른 표면과 같은 `CloverBalance`다. */}
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <span>남은 클로버</span>
            <CloverBalance balance={balance} />
          </p>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end(false)}>
              그만두기
            </Button>
            <Button type="button" onClick={() => call.end(true)}>
              계속하기
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
