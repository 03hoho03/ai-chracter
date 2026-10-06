import { useState } from "react";

import {
  ChapterModelSelect,
  chapterModelCost,
  type NovelChapterModel,
  type NovelChapterModelId,
} from "@/entities/novel";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { NovelSpendDialog } from "./NovelSpendDialog";

type ConfirmChapterSpendModalProps = {
  title: string;
  /** 무엇이 일어나는가. 금액 줄은 모달이 붙이므로 여기 적지 않는다. */
  description: string;
  /** 실행 버튼 라벨 — "확인" 이 아니라 무슨 일이 일어나는지를 말한다. */
  confirmLabel: string;
  /** 어느 가격을 보일지 — 장 만들기와 다시 만들기는 가격 칸이 따로다. */
  kind: "generate" | "regenerate";
  /** 서버가 준 고를 수 있는 모델과 가격(상세의 `chapterModels`). 하나뿐이면 모델 선택이 그려지지 않는다. */
  models: NovelChapterModel[];
  initialModelId: NovelChapterModelId;
  /** 모델 목록이 없는 서버일 때의 금액(상세의 `prices`). */
  fallbackCost: number;
};

/** 장 작업(다시 만들기)의 금액 확인 + 글쓰기 모델 선택. 소설 상위 모델 허용이 없는 계정은 모델이 하나뿐이라 선택이
 * 그려지지 않아 `ConfirmNovelSpendModal` 과 똑같이 보인다.
 *
 * 확정하면 고른 모델과 이용자가 본 금액을 돌려준다 — 요청의 `expectedCost` 가 화면의 숫자와 같아야 서버 단가 대조가
 * 뜻을 갖는다. 그만두면 `null` 이다. */
export const ConfirmChapterSpendModal = createCallable<
  ConfirmChapterSpendModalProps,
  { model: NovelChapterModelId; cost: number } | null
>(({ call, title, description, confirmLabel, kind, models, initialModelId, fallbackCost }) => {
  const [modelId, setModelId] = useState(initialModelId);
  const cost = chapterModelCost(models, modelId, kind, fallbackCost);

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
      <ChapterModelSelect models={models} value={modelId} onValueChange={setModelId} kind={kind} />
    </NovelSpendDialog>
  );
});
