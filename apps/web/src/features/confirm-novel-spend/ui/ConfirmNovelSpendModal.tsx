import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";

import { CloverSpendSummary, useCloverBalanceQuery } from "@/entities/clover";
import { createCallable } from "@/shared/lib/callable/createCallable";

type ConfirmNovelSpendModalProps = {
  title: string;
  /** 무엇이 일어나는가. 금액 줄은 모달이 붙이므로 여기 적지 않는다. */
  description: string;
  /** 서버 상세의 단가. 요청의 `expectedCost` 로도 같은 값을 싣는다. */
  cost: number;
  /** 실행 버튼 라벨 — "확인" 이 아니라 무슨 일이 일어나는지를 말한다. */
  confirmLabel: string;
};

/** 소설 작업(장 재생성·AI 수정)에 클로버를 쓰기 전에 매번 금액을 보이고 동의를 받는다. 채팅·이미지의
 * `ConfirmCloverSpendModal` 과 모양은 같지만 다시 쓰지 않는다 — 그쪽은 "오늘 무료 한도를 다 썼다"는 하루 한 번
 * 동의라 무료분이 없는 소설 작업에서는 문장 전체가 거짓이 된다.
 *
 * 확정 뒤 동작(어느 라우트를 부르고 어떤 작업을 지켜볼지)이 호출부마다 달라 `Promise<boolean>` 만 돌려준다.
 * 잔액은 모달이 직접 읽는다 — 호출부가 미리 받아 넘기면 열 때마다 같은 조회를 호출부마다 되풀이한다. 못 받았으면
 * 금액만 보이고 동의는 막지 않는다(정확한 판정은 서버가 차감 전에 한다).
 *
 * 버튼 순서는 `취소` 먼저다(DOM·시각·탭 셋이 같다, 푸터 프리미티브가 강제). `bg-muted` 를 쓰지 않는다 — 모달
 * 표면(`popover`)과 값이 같아 사라진다. */
export const ConfirmNovelSpendModal = createCallable<ConfirmNovelSpendModalProps, boolean>(
  ({ call, title, description, cost, confirmLabel }) => {
    const { data: clover } = useCloverBalanceQuery();

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="break-keep">{title}</DialogTitle>
            <DialogDescription className="break-keep">{description}</DialogDescription>
          </DialogHeader>

          <CloverSpendSummary cost={cost} balance={clover?.balance} />

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end(false)}>
              취소
            </Button>
            <Button type="button" onClick={() => call.end(true)}>
              {confirmLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
