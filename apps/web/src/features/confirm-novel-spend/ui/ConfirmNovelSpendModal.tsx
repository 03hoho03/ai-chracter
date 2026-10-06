import { createCallable } from "@/shared/lib/callable/createCallable";

import { NovelSpendDialog } from "./NovelSpendDialog";

type ConfirmNovelSpendModalProps = {
  title: string;
  /** 무엇이 일어나는가. 금액 줄은 모달이 붙이므로 여기 적지 않는다. */
  description: string;
  /** 서버 상세의 단가. 요청의 `expectedCost` 로도 같은 값을 싣는다. */
  cost: number;
  /** 실행 버튼 라벨 — "확인" 이 아니라 무슨 일이 일어나는지를 말한다. */
  confirmLabel: string;
};

/** 소설 작업(AI 수정)에 클로버를 쓰기 전에 매번 금액을 보이고 동의를 받는다. 채팅·이미지의
 * `ConfirmCloverSpendModal` 과 모양은 같지만 다시 쓰지 않는다 — 그쪽은 "오늘 무료 한도를 다 썼다"는 하루 한 번
 * 동의라 무료분이 없는 소설 작업에서는 문장 전체가 거짓이 된다.
 *
 * 모델을 고르지 않는다 — AI 수정은 고른 모델과 무관하게 기본 모델이 쓴다. 모델을 고르는 장 확인은
 * `ConfirmChapterSpendModal` 이고, 둘이 다른 모달이라 이 화면에 모델 선택이 섞일 길이 없다.
 *
 * 확정 뒤 동작(어느 라우트를 부르고 어떤 작업을 지켜볼지)이 호출부마다 달라 `Promise<boolean>` 만 돌려준다. */
export const ConfirmNovelSpendModal = createCallable<ConfirmNovelSpendModalProps, boolean>(
  ({ call, title, description, cost, confirmLabel }) => (
    <NovelSpendDialog
      isOpen={!call.ended}
      title={title}
      description={description}
      cost={cost}
      confirmLabel={confirmLabel}
      onCancel={() => call.end(false)}
      onConfirm={() => call.end(true)}
    />
  ),
);
