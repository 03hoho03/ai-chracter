type FailureAlertProps = {
  message: string;
};

/** 대화상자 안의 실패 문단. 나타나는 순간 이 문단으로 포커스를 옮긴다 — 보내는 동안 확정 버튼이 비활성이 되며 포커스가 `<body>` 로
 * 떨어지고, 긴 대화상자에서는 문단이 본문 스크롤 영역 아래에 생겨 보이지 않기 때문이다. 같은 실패가 다시 나도 보낼 때 문단이 사라졌다
 * 다시 생겨 또 옮긴다. */
export function FailureAlert({ message }: FailureAlertProps) {
  return (
    <p ref={focusOnMount} tabIndex={-1} role="alert" className="text-sm break-keep text-destructive-text outline-none">
      {message}
    </p>
  );
}

/** 모듈 수준 함수라 참조가 바뀌지 않아 React 가 붙을 때 한 번만 부른다(인라인 함수면 그릴 때마다 다시 불러 입력 중에도 포커스를
 * 빼앗는다). */
function focusOnMount(element: HTMLParagraphElement | null) {
  element?.focus();
}
