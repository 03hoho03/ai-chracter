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
  ["이에요", "예요"],
  ["이다", "다"],
  ["이나", "나"],
  ["이며", "며"],
  ["이고", "고"],
  ["이라고", "라고"],
  ["이라서", "라서"],
  ["이야", "야"],
] as const;
type ParticlePair = (typeof PARTICLE_PAIRS)[number];

const PARTICLE_BY_FORM = new Map<string, ParticlePair>(
  PARTICLE_PAIRS.flatMap((pair) => pair.map((form) => [form, pair] as const)),
);
// `야` 는 부르는 말과 서술격 두 쌍에 있다. 작가가 쓴 `야` 는 부르는 말로 읽는다 — 서술격은 `이야` 로 쓴다.
PARTICLE_BY_FORM.set("야", ["아", "야"]);
// 매크로와 조사 사이에 올 수 있는 닫는 따옴표 한 글자.
const CLOSING_MARKS = `'’"”」』`;
// 닫는 따옴표 뒤에서는 직접 인용 조사라 고치지 않는 형태.
const QUOTATIVE_FORMS = new Set(["이라고", "라고"]);
const MACRO = new RegExp(
  String.raw`\{\{[ \t]*([A-Za-z]+)[ \t]*\}\}(?:([${CLOSING_MARKS}])?(${[...PARTICLE_BY_FORM.keys()].join("|")})(?![가-힣]))?`,
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
    (
      match,
      macro: string,
      mark: string | undefined,
      written: string | undefined,
    ) => {
      const name = byMacro.get(macro.toLowerCase());
      if (name === undefined || name === null) return match;
      if (written === undefined) return name;
      if (mark !== undefined && QUOTATIVE_FORMS.has(written))
        return name + mark + written;
      return name + (mark ?? "") + particleFor(name, written);
    },
  );
}
