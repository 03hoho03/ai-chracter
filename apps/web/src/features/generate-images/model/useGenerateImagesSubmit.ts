import { createContext, useContext } from "react";

import type { UnavailableReason } from "../ui/GenerateImagesUnavailableState";
import type { GenerateImagesFormValues } from "./schema";

/** 참조 행이 피커에서 받는 값. 미리보기 URL은 표시 전용이라 폼에 넣지 않는다. */
export type PickedReferenceImage = { assetId: string; imageUrl: string };

/** 제출을 소유한 셸이 폼 바깥에서 쓰는 두 가지. 셸은 폼 인스턴스를 갖지 않으므로(폼은 프로바이더
 * 안의 `useForm`이다) 참조를 비우는 일도 프로바이더가 콜백으로 건넨다 — 서버가 참조를 거절했을 때
 * 비우지 않으면 다음 제출이 같은 오류로 되풀이된다.
 *
 * `errorMessage`를 주면 참조 필드 아래에 그 문구를 필드 오류로 건다. 사용자가 다시 골라야 풀리는
 * 거절이라 사라지는 토스트보다 고칠 자리 옆에 남는 편이 맞다. 오류는 다시 고르거나 다음에 제출하면
 * 풀린다(그 이유는 `GenerateImagesReferenceField`의 오류 문단 주석). */
export type GenerateImagesSubmitHelpers = {
  isReferenceEnabled: boolean;
  clearReference: (errorMessage?: string) => void;
};

export type GenerateImagesSubmitContextValue = {
  onSubmit: (values: GenerateImagesFormValues) => void | Promise<void>;
  isModelsPending: boolean;
  // 브라우저 실검증 회귀 수정 — 예전엔 이 판정이 early return으로 children 전체(탭 스트립·트리거·
  // 좌우열까지)를 대체 화면으로 바꿔치기했다(3열 셸에서 실측: 이용 불가 상태가 되면 <aside>도
  // 시트 트리거도 통째로 사라져 lg 미만에서 보관함을 열 방법이 없어졌다). 판정 로직은 그대로 두고
  // 결과만 context로 내려, 소비 측(중앙 열)이 그 자리에서만 대체 UI를 꽂게 한다.
  unavailableReason: UnavailableReason | undefined;
  onRetry: (() => void) | undefined;
  /** 고른 모델이 참조 이미지를 받는가. 꺼지면 참조 행이 통째로 숨는다. */
  isReferenceEnabled: boolean;
  /** 본인 생성 이미지 피커를 연다. 피커는 다른 feature 슬라이스라 이 슬라이스가 직접 import하지 않고
   * 셸(위젯)이 주입한다. 닫으면 `undefined`. */
  onPickReference: () => Promise<PickedReferenceImage | undefined>;
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
