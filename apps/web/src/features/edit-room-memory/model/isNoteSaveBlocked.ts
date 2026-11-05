type NoteSaveState = {
  isSavePending: boolean;
  isClearPending: boolean;
  isSubmitting: boolean;
};

/** "꼭 기억할 것" [저장]을 막을지. 버튼의 비활성 표시와 클릭 가드가 이 값 하나를 함께 본다 — 둘이 따로 계산되면 흐리게
 * 보이는데 눌리거나 그 반대가 된다. 비우기가 도는 동안에도 막는다: 그 사이 저장이 나가면 비운 결과 위에 옛 노트가 다시
 * 저장된다. */
export function isNoteSaveBlocked({ isSavePending, isClearPending, isSubmitting }: NoteSaveState): boolean {
  return isSavePending || isClearPending || isSubmitting;
}
