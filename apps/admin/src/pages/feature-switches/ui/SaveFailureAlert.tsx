/** 저장 실패(선행 조건 거절·결과를 모르는 실패) 문단. 나타나는 순간 이 문단으로 포커스를 옮긴다 — 긴 확인 모달에서는 문단이
 * 본문 스크롤 영역 아래에 생겨 보이지 않고, 저장 중에 비활성이 됐던 확정 버튼이 포커스를 잃어 `<body>` 로 떨어지기 때문이다.
 * 포커스가 스크롤 영역을 문단까지 내린다. 같은 실패가 다시 나도 저장을 누를 때 문단이 사라졌다 다시 생겨 또 옮긴다. */
export function SaveFailureAlert({ message }: { message: string }) {
  return (
    <p ref={focusOnMount} tabIndex={-1} role="alert" className="text-sm break-keep text-destructive-text outline-none">
      {message}
    </p>
  );
}

/** 모듈 수준 함수라 참조가 바뀌지 않아 React 가 붙을 때 한 번만 부른다(인라인 함수면 그릴 때마다 다시 불러 사유를 적는 중에도
 * 포커스를 빼앗는다). */
function focusOnMount(element: HTMLParagraphElement | null) {
  element?.focus();
}
