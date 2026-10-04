type GenerateButtonInput = {
  /** 폼 제출이 진행 중인가(202 전). */
  isSubmitting: boolean;
  /** 모델 목록을 아직 받는 중인가 — 모델·스타일이 비어 있어 제출해도 검증이 조용히 막는다. */
  isModelsPending: boolean;
  /** 202 를 받은 잡이 아직 끝나지 않았는가. */
  isJobInProgress: boolean;
};

/** 생성 버튼의 잠금과 표시. `isBlocked` 는 셋 중 하나라도 참이면 잠근다. `isGenerating` 은 라벨을
 * "생성 중…"으로 바꿀지인데, 모델 목록 로딩은 생성이 아니므로 잠그기만 하고 라벨은 그대로 둔다.
 *
 * 잡이 끝나기 전에 잠그는 이유: 서버는 사용자당 잡을 하나만 받아 진행 중 재제출은 429 로 끝나고,
 * 결과는 새 잡이 받아들여질 때만 바뀌므로 눌러도 얻는 것이 없다. */
export function getGenerateButtonState({ isSubmitting, isModelsPending, isJobInProgress }: GenerateButtonInput): {
  isBlocked: boolean;
  isGenerating: boolean;
} {
  const isGenerating = isSubmitting || isJobInProgress;
  return { isBlocked: isGenerating || isModelsPending, isGenerating };
}

/** 결과 타일의 접근 이름. `position` 은 1부터 센 칸 순서, `total` 은 요청한 장수다. */
export function getResultTileLabel(position: number, total: number): string {
  return `생성 결과 ${position}/${total} 상세 보기`;
}
