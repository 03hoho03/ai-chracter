/**
 * 작가 글 속 `{{user}}`·`{{char}}` 치환의 Worker 사본. 규칙의 원본은 앱의 `src/shared/lib/text/authorMacros.ts` 이고
 * (서버 `apps/api/src/api/content/author_macros.py` 와 같은 규칙), Worker 는 `src/` 를 가져오지 못해 사본을 둔다 —
 * 세 구현을 같은 입력 표(`apps/api/tests/fixtures/author_macro_cases.json`)로 시험해 갈라지지 않게 한다.
 * 문법·조사 보정 규칙의 설명은 원본에 있다.
 */

/** 대화 프로필도 작품 기본 이름도 없을 때 쓰는 이름. */
export const FALLBACK_USER_NAME = "당신";

// [받침 있는 이름 뒤의 형태, 받침 없는 이름 뒤의 형태]
const PARTICLE_PAIRS = [
  ["은", "는"],
  ["이", "가"],
  ["을", "를"],
  ["과", "와"],
  ["아", "야"],
  ["이랑", "랑"],
  ["으로", "로"],
] as const;
type ParticlePair = (typeof PARTICLE_PAIRS)[number];

const PARTICLE_BY_FORM = new Map<string, ParticlePair>(
  PARTICLE_PAIRS.flatMap((pair) => pair.map((form) => [form, pair] as const)),
);
const MACRO = new RegExp(
  String.raw`\{\{[ \t]*([A-Za-z]+)[ \t]*\}\}(?:(${[...PARTICLE_BY_FORM.keys()].join("|")})(?![가-힣]))?`,
  "g",
);

const HANGUL_FIRST = "가".charCodeAt(0);
const HANGUL_LAST = "힣".charCodeAt(0);
const RIEUL_FINAL = 8; // 한글 음절의 종성 번호에서 ㄹ

function particleFor(name: string, written: string): string {
  const code = name.charCodeAt(name.length - 1);
  const pair = PARTICLE_BY_FORM.get(written);
  if (!(code >= HANGUL_FIRST && code <= HANGUL_LAST) || pair === undefined)
    return written;
  const final = (code - HANGUL_FIRST) % 28;
  const [withFinal, withoutFinal] = pair;
  if (final === 0 || (final === RIEUL_FINAL && withFinal === "으로"))
    return withoutFinal;
  return withFinal;
}

/** `{{user}}` 를 `userName` 으로, `{{char}}` 를 `charName` 으로 바꾸고 바로 뒤 조사를 맞춘다. `charName` 이 null 이면 `{{char}}` 를 둔다. */
export function expandAuthorMacros(
  text: string,
  names: { userName: string; charName: string | null },
): string {
  const byMacro = new Map([
    ["user", names.userName],
    ["char", names.charName],
  ]);
  return text.replace(
    MACRO,
    (match, macro: string, written: string | undefined) => {
      const name = byMacro.get(macro.toLowerCase());
      if (name === undefined || name === null) return match;
      return written === undefined ? name : name + particleFor(name, written);
    },
  );
}
