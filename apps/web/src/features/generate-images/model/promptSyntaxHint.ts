// image-style-7-goal-prompt.md IS-10 — 가중치 문법 안내와 괄호 경고를 한 줄로 합친다(평소↔경고
// 전환). zod에 넣지 않는다 — zod는 통과/실패 이분법이고 이 경고는 제출을 막지 않는다(계약: "에러가
// 되지는 않지만 결과에 영향을 줄 수 있다"). 순수 함수로 뽑아 `GenerateImagesPromptField`가
// `useWatch` 렌더 시점에 호출한다(fe-state-data — 파생 상태는 useEffect가 아니라 렌더 중 계산).
//
// 괄호 판정 규칙은 image-style-7-followup.md IS-22(집 PC 실측 회신, 2026-09-15)로 확정됐다.
// 갈림길은 언어가 아니라 "(" 바로 앞 글자다 — 공백·쉼표·문장 시작이면 문법으로 읽혀 제거되고
// (평문과 비트 단위로 동일), 앞 글자에 바로 붙으면(소녀(, abc() 그 덩어리만 리터럴이 된다(한글·영문
// 동일). 이 파일이 보는 경고는 3종:
//   ① ASCII 괄호 짝 불일치 — 리터럴로 들어가 평문 대비 diff 7.7~9.0.
//   ② 전각 괄호(U+FF08 （ / U+FF09 ）) 포함 — 짝이 맞아도 무조건 리터럴이라 가중치가 안 먹고
//      (diff 15.11), 토큰을 최대 7배 먹는다. 문자 검출만으로 끝난다 — 짝을 맞춰볼 필요도,
//      파싱할 필요도 없다.
//   ③ "문자(...)숫자" — "(" 가 앞 글자에 붙으면 전체가 리터럴이 되어 가중치가 전혀 안 먹는다.
//      가중치 숫자가 붙은 경우로만 경고한다 — 숫자가 없으면(예: "소녀(단발), 교복") 리터럴이 되어도
//      그 설명 의도가 프롬프트에 그대로 남아 경고 대상이 아니다.
// 우선순위는 ② > ③ > ①이다 — ②의 실질 피해(토큰 최대 7배)가 가장 크다.
export const PROMPT_WEIGHT_SYNTAX_HINT =
  "괄호로 강조할 부분을 감싸고 숫자를 붙이면 가중치를 줄 수 있어요. 예: (강조할 부분)1.3 · 권장 1.2~1.5";

export const PROMPT_UNBALANCED_PARENS_WARNING =
  "괄호 짝이 맞지 않아요. (강조할 부분)1.3처럼 여는 괄호와 닫는 괄호를 짝지어주세요.";

export const PROMPT_FULLWIDTH_PARENS_WARNING =
  "전각 괄호 （）는 인식되지 않아요. 반각 괄호 ()로 바꿔주세요.";

export const PROMPT_ATTACHED_PAREN_WEIGHT_WARNING =
  "앞 글자에 붙은 괄호는 가중치가 적용되지 않아요. 소녀 (단발)1.4처럼 앞에 공백을 넣어주세요.";

function hasFullwidthParens(prompt: string): boolean {
  return /[（）]/.test(prompt);
}

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

// openIndex의 "("과 짝이 되는 ")"의 인덱스를 깊이 추적으로 찾는다. 없으면 -1(짝 불일치는 ①이 처리).
function findMatchingParenEnd(prompt: string, openIndex: number): number {
  let depth = 0;
  for (let i = openIndex; i < prompt.length; i += 1) {
    if (prompt[i] === "(") {
      depth += 1;
    } else if (prompt[i] === ")") {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  return -1;
}

// "문자(...)숫자" 패턴: "(" 바로 앞 글자가 공백·쉼표·문장 시작이 아니면 그 괄호 덩어리는 리터럴이
// 되고, 가중치 숫자가 뒤에 붙어 있으면 그 숫자가 전혀 적용되지 않는다. 중첩 괄호(예: "((tag))1.4")는
// 짝 매칭이 안쪽부터 닫히므로 바깥 "(" 만 문장 시작 여부로 걸러지면 자연히 경고 대상에서 빠진다.
function hasAttachedParenWeight(prompt: string): boolean {
  for (let i = 0; i < prompt.length; i += 1) {
    if (prompt[i] !== "(") continue;
    const prev = prompt[i - 1];
    if (prev === undefined || /\s/.test(prev) || prev === ",") continue;
    const closeIndex = findMatchingParenEnd(prompt, i);
    if (closeIndex === -1) continue;
    if (/^\d/.test(prompt.slice(closeIndex + 1))) return true;
  }
  return false;
}

export function getPromptSyntaxHint(prompt: string): string {
  if (hasFullwidthParens(prompt)) return PROMPT_FULLWIDTH_PARENS_WARNING;
  if (hasAttachedParenWeight(prompt)) return PROMPT_ATTACHED_PAREN_WEIGHT_WARNING;
  if (hasUnbalancedParens(prompt)) return PROMPT_UNBALANCED_PARENS_WARNING;
  return PROMPT_WEIGHT_SYNTAX_HINT;
}
