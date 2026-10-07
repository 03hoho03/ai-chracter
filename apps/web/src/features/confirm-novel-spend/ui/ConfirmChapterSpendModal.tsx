import { useState } from "react";

import {
  ChapterModelSelect,
  type NovelChapterModelId,
  type PricedChapterModelOption,
} from "@/entities/novel";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { NovelSpendDialog } from "./NovelSpendDialog";

type ConfirmChapterSpendModalProps = {
  title: string;
  /** 무엇이 일어나는가. 금액 줄은 모달이 붙이므로 여기 적지 않는다. */
  description: string;
  /** 실행 버튼 라벨 — "확인" 이 아니라 무슨 일이 일어나는지를 말한다. */
  confirmLabel: string;
  /** 고를 수 있는 모델과 그 모델로 이 동작을 할 때의 금액 — 서버가 계산한 값 그대로다. 하나뿐이면 모델 선택이
   * 그려지지 않는다. 맞지 않는 모델은 비활성 + 이유로 보인다. */
  options: PricedChapterModelOption[];
  /** 열 때 골라 둘 모델. 고를 수 있는 항목이어야 한다(호출부가 `initialChapterModelId` 로 고른다). */
  initialModelId: NovelChapterModelId;
};

/** 화 작업(다시 만들기)의 금액 확인 + 글쓰기 모델 선택. 소설 상위 모델 허용이 없는 계정은 모델이 하나뿐이라 선택이
 * 그려지지 않아 `ConfirmNovelSpendModal` 과 똑같이 보인다.
 *
 * 확정하면 고른 모델과 이용자가 본 금액을 돌려준다 — 요청의 `expectedCost` 가 화면의 숫자와 같아야 서버 금액 대조가
 * 뜻을 갖는다. 금액은 서버가 그 동작에 매긴 값을 그대로 쓴다 — 화면에서 화 수와 단가를 곱하면 서버 계산과 갈라질 때
 * 확인할 때마다 409 가 된다. 그만두면 `null` 이다. */
export const ConfirmChapterSpendModal = createCallable<
  ConfirmChapterSpendModalProps,
  { model: NovelChapterModelId; cost: number } | null
>(({ call, title, description, confirmLabel, options, initialModelId }) => {
  const [modelId, setModelId] = useState(initialModelId);
  const cost = options.find((option) => option.id === modelId)?.cost ?? 0;

  return (
    <NovelSpendDialog
      isOpen={!call.ended}
      title={title}
      description={description}
      cost={cost}
      confirmLabel={confirmLabel}
      onCancel={() => call.end(null)}
      onConfirm={() => call.end({ model: modelId, cost })}
    >
      <ChapterModelSelect options={options} value={modelId} onValueChange={setModelId} />
    </NovelSpendDialog>
  );
});
