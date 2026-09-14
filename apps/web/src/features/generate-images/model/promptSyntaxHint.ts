// image-style-7-goal-prompt.md IS-10 — 가중치 문법 안내와 괄호 짝 경고를 한 줄로 합친다(평소↔경고
// 전환). zod에 넣지 않는다 — zod는 통과/실패 이분법이고 이 경고는 제출을 막지 않는다(계약: "에러가
// 되지는 않지만 결과에 영향을 줄 수 있다"). 순수 함수로 뽑아 `GenerateImagesPromptField`가
// `useWatch` 렌더 시점에 호출한다(fe-state-data — 파생 상태는 useEffect가 아니라 렌더 중 계산).
//
// 괄호 판정 규칙은 잠정이다(image-style-7-goal-prompt.md §4-2, progress §4-2 — 집 PC 회신 대기).
// ASCII `(`/`)`의 짝 불일치만 본다. 중첩·숫자 유무·전각 괄호(（）)는 보지 않는다.
export const PROMPT_WEIGHT_SYNTAX_HINT =
  "괄호로 강조할 부분을 감싸고 숫자를 붙이면 가중치를 줄 수 있어요. 예: (강조할 부분)1.3 · 권장 1.2~1.5";

export const PROMPT_UNBALANCED_PARENS_WARNING =
  "괄호 짝이 맞지 않아요. (강조할 부분)1.3처럼 여는 괄호와 닫는 괄호를 짝지어주세요.";

function hasUnbalancedParens(prompt: string): boolean {
  let depth = 0;
  for (const char of prompt) {
    if (char === "(") {
      depth += 1;
    } else if (char === ")") {
      depth -= 1;
      if (depth < 0) return true; // 닫는 괄호가 여는 괄호보다 먼저 나온 경우
    }
  }
  return depth !== 0;
}

export function getPromptSyntaxHint(prompt: string): string {
  return hasUnbalancedParens(prompt) ? PROMPT_UNBALANCED_PARENS_WARNING : PROMPT_WEIGHT_SYNTAX_HINT;
}
