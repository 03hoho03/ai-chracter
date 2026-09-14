import { zodResolver } from "@hookform/resolvers/zod";
import { createContext, useContext, useEffect, useRef, type ReactNode } from "react";
import { FormProvider, useForm } from "react-hook-form";

import { useImageModelsQuery } from "@/entities/image-model";

import {
  generateImagesDefaultValues,
  generateImagesSchema,
  type GenerateImagesFormValues,
} from "../model/schema";
import type { UnavailableReason } from "./GenerateImagesUnavailableState";

type GenerateImagesFormProviderProps = {
  onSubmit: (values: GenerateImagesFormValues) => void | Promise<void>;
  children: ReactNode;
};

type GenerateImagesSubmitContextValue = {
  onSubmit: GenerateImagesFormProviderProps["onSubmit"];
  isModelsPending: boolean;
  // 브라우저 실검증 회귀 수정 — 예전엔 이 판정이 early return으로 children 전체(탭 스트립·트리거·
  // 좌우열까지)를 대체 화면으로 바꿔치기했다(3열 셸에서 실측: 이용 불가 상태가 되면 <aside>도
  // 시트 트리거도 통째로 사라져 lg 미만에서 보관함을 열 방법이 없어졌다). 판정 로직은 그대로 두고
  // 결과만 context로 내려, 소비 측(중앙 열)이 그 자리에서만 대체 UI를 꽂게 한다.
  unavailableReason: UnavailableReason | null;
  onRetry: (() => void) | undefined;
};

// image-refact-techspec.md IT-9 — `<form>` 엘리먼트는 GenerateImagesPromptField(중앙 열)가 감싸지만
// 제출 콜백과 모델 로딩 상태는 이 프로바이더가 쥔다. react-hook-form의 FormProvider context는 폼
// 값만 나르므로, 그 바깥의 사업 로직을 함께 내리는 별도 context가 필요하다.
const GenerateImagesSubmitContext = createContext<GenerateImagesSubmitContextValue | null>(null);

export function useGenerateImagesSubmit() {
  const value = useContext(GenerateImagesSubmitContext);
  if (value == null) {
    throw new Error("useGenerateImagesSubmit은 GenerateImagesFormProvider 안에서만 쓸 수 있다");
  }
  return value;
}

// US-008 / image-refact-techspec.md IT-9 — 옛 GenerateImagesForm이 갖고 있던 useForm 초기화·모델
// 목록 조회·기본값 자동 적용·불가용 상태 분기를 그대로 옮겼다. 나머지 필드 UI(프롬프트·스타일
// 그리드·모델/비율/개수)는 이 프로바이더 아래 세 조각으로 쪼개졌다.
export function GenerateImagesFormProvider({ onSubmit, children }: GenerateImagesFormProviderProps) {
  const {
    data: models,
    isPending: isModelsPending,
    isError: isModelsError,
    refetch: refetchModels,
  } = useImageModelsQuery();

  const form = useForm<GenerateImagesFormValues>({
    resolver: zodResolver(generateImagesSchema),
    defaultValues: generateImagesDefaultValues,
  });
  const { getValues, reset } = form;

  // model/style 기본값은 스키마에 없다(LT-9) — 목록이 처음 로드되면 첫 가용 모델/스타일로 한 번만
  // reset()한다. 이후 배경 refetch에서는(가용성이 바뀌어도) 다시 손대지 않는다 — 사용자가 이미 고른
  // 값을 조용히 되돌리면 그게 더 놀랍다(LT-9b, `reset()` 선례가 이 저장소에 없어 새로 만든 흐름).
  const hasAppliedModelDefaultsRef = useRef(false);
  useEffect(() => {
    if (hasAppliedModelDefaultsRef.current || models === undefined) return;
    const firstAvailable = models.find((model) => model.available);
    if (firstAvailable == null) return;
    hasAppliedModelDefaultsRef.current = true;
    // styles[0]은 레지스트리 순서에 기대는 것이라 스타일이 여럿이고 그중 앞쪽이 available: false면
    // 깨진다 — 가용한 첫 스타일을 명시적으로 찾는다.
    reset({
      ...getValues(),
      model: firstAvailable.id,
      style: firstAvailable.styles.find((style) => style.available)?.id ?? "",
    });
  }, [models, getValues, reset]);

  const availableModels = models?.filter((model) => model.available) ?? [];

  let unavailableReason: UnavailableReason | null = null;
  let onRetry: (() => void) | undefined;
  // 배경 refetch 실패(staleTime 30s + refetchOnWindowFocus 기본값)에도 query-core의 'error' reducer는
  // 이전 data를 지우지 않는다 — 그래서 models가 남아 있으면(낡았어도) 화면을 갈아엎지 않고 폼을 그대로
  // 보여준다. LG-8("사전 헬스체크 + 즉시 실패")과 모순되지 않는다: 로컬 비가동은 *성공한* 쿼리가
  // `available: false`를 실어 오는 값이라 아래 unavailable 분기가 잡는다. 여기는 쿼리 자체가 실패해
  // "그런지 아닌지도 모른다"이고, 그건 보여줄 게 없을 때만 화면을 대체할 가치가 있다.
  if (isModelsError && models === undefined) {
    unavailableReason = "error";
    onRetry = () => void refetchModels();
  } else if (models !== undefined && models.length === 0) {
    // (LG-17) models 쿼리의 선행 갭 — 빈 목록과 전 모델 일시 불가는 전에는 "활성화된 빈 Select + 낡은
    // 기본값 + 제출 가능"으로 조용히 깨졌다. 둘 다 제출 이전 상태로 이름을 준다.
    unavailableReason = "empty";
  } else if (models !== undefined && availableModels.length === 0) {
    unavailableReason = "unavailable";
    onRetry = () => void refetchModels();
  }

  return (
    <FormProvider {...form}>
      <GenerateImagesSubmitContext.Provider value={{ onSubmit, isModelsPending, unavailableReason, onRetry }}>
        {children}
      </GenerateImagesSubmitContext.Provider>
    </FormProvider>
  );
}
