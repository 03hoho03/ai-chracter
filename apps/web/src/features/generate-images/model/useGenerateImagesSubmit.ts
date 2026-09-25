import { createContext, useContext } from "react";

import type { UnavailableReason } from "../ui/GenerateImagesUnavailableState";
import type { GenerateImagesFormValues } from "./schema";

export type GenerateImagesSubmitContextValue = {
  onSubmit: (values: GenerateImagesFormValues) => void | Promise<void>;
  isModelsPending: boolean;
  // 브라우저 실검증 회귀 수정 — 예전엔 이 판정이 early return으로 children 전체(탭 스트립·트리거·
  // 좌우열까지)를 대체 화면으로 바꿔치기했다(3열 셸에서 실측: 이용 불가 상태가 되면 <aside>도
  // 시트 트리거도 통째로 사라져 lg 미만에서 보관함을 열 방법이 없어졌다). 판정 로직은 그대로 두고
  // 결과만 context로 내려, 소비 측(중앙 열)이 그 자리에서만 대체 UI를 꽂게 한다.
  unavailableReason: UnavailableReason | undefined;
  onRetry: (() => void) | undefined;
};

// `<form>` 엘리먼트는 GenerateImagesPromptField(중앙 열)가 감싸지만
// 제출 콜백과 모델 로딩 상태는 GenerateImagesFormProvider가 쥔다. react-hook-form의 FormProvider
// context는 폼 값만 나르므로, 그 바깥의 사업 로직을 함께 내리는 별도 context가 필요하다.
export const GenerateImagesSubmitContext = createContext<GenerateImagesSubmitContextValue | null>(null);

export function useGenerateImagesSubmit() {
  const value = useContext(GenerateImagesSubmitContext);
  if (value == null) {
    throw new Error("useGenerateImagesSubmit은 GenerateImagesFormProvider 안에서만 쓸 수 있다");
  }
  return value;
}
