/**
 * 작가 글 속 `{{user}}`·`{{char}}` 를 이름으로 바꾸는 순수 함수. 규칙은 서버(`apps/api/src/api/content/author_macros.py`)와
 * 같다 — 프롬프트는 서버가, 화면은 이 함수가 바꾸므로 두 구현이 갈라지면 모델이 부른 이름과 화면의 이름이 다르다
 * (같은 입력 표로 양쪽을 시험한다).
 *
 * 문법
 * - 이중 중괄호 안의 `user`·`char`, 대소문자 무시. 중괄호 안쪽 앞뒤의 공백·탭은 허용한다(줄바꿈은 아니다). 글자는
 *   ASCII 로만 비교한다 — 유니코드 대소문자 접기는 `ſ`→`s` 처럼 언어마다 결과가 달라 서버 구현과 갈라진다.
 * - 한 번에 훑고 끝난다. 바꿔 넣은 이름 속의 `{{char}}`·`{{img::…}}` 는 다시 읽지 않는다. 이미지 태그는 이 문법에
 *   맞지 않아 손대지 않는다 — 이름이 태그가 되지 않게, 호출부는 태그 처리를 먼저 하고 이 함수를 나중에 부른다.
 * - 스토리(`charName` 이 null)에는 `{{char}}` 가 가리킬 한 사람이 없다. 몰래 지우면 작가가 모르므로 글자 그대로 둔다.
 *
 * 조사 보정
 * - 매크로 바로 뒤에 `은/는·이/가·을/를·과/와·아/야·이랑/랑·으로/로` 중 하나가 있고 그 뒤가 한글 음절이 아니거나
 *   글 끝일 때만, 이름의 끝 글자 받침에 맞는 쪽으로 바꾼다. 작가가 어느 쪽을 썼든 바꾼다(이름은 읽는 사람마다 다르다).
 *   뒤가 한글 음절이면 낱말의 일부일 수 있어(`{{user}}가방`) 그대로 둔다. 같은 경계 검사 덕에 `이랑` 이 `이` 로
 *   읽히는 일도 없다(`이` 뒤의 `랑` 이 한글이라 짧은 쪽은 맞지 않는다).
 * - ㄹ 받침 뒤에는 `으로` 가 아니라 `로` 가 맞다.
 * - 이름 끝 글자가 한글 음절이 아니면(`Alex`, `R2`) 받침을 알 수 없어 작가가 쓴 조사를 그대로 둔다.
 */

/** 대화 프로필도 작품 기본 이름도 없을 때 쓰는 이름. 이름 고르기는 호출부가 하고, 이 값만 여기서 정한다. */
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
const PARTICLE_ALTERNATION = [...PARTICLE_BY_FORM.keys()].join("|");
const MACRO = new RegExp(
  String.raw`\{\{[ \t]*([A-Za-z]+)[ \t]*\}\}(?:(${PARTICLE_ALTERNATION})(?![가-힣]))?`,
  "g",
);

const HANGUL_FIRST = "가".charCodeAt(0);
const HANGUL_LAST = "힣".charCodeAt(0);
const RIEUL_FINAL = 8; // 한글 음절의 종성 번호에서 ㄹ

/** 이름 끝 글자의 종성 번호(0 = 받침 없음). 끝 글자가 한글 음절이 아니면 undefined. */
function finalConsonant(name: string): number | undefined {
  const code = name.charCodeAt(name.length - 1);
  if (!(code >= HANGUL_FIRST && code <= HANGUL_LAST)) return undefined;
  return (code - HANGUL_FIRST) % 28;
}

function particleFor(name: string, written: string): string {
  const final = finalConsonant(name);
  const pair = PARTICLE_BY_FORM.get(written);
  if (final === undefined || pair === undefined) return written;
  const [withFinal, withoutFinal] = pair;
  if (final === 0 || (final === RIEUL_FINAL && withFinal === "으로"))
    return withoutFinal;
  return withFinal;
}

/**
 * 작가 글의 `{{user}}` 를 `userName` 으로, `{{char}}` 를 `charName` 으로 바꾸고 바로 뒤 조사를 맞춘다.
 * `userName` 은 호출부가 이미 고른 이름이다(대화 프로필 → 작품 기본 이름 → `FALLBACK_USER_NAME`).
 * `charName` 이 null 이면 스토리라 `{{char}}` 를 글자 그대로 둔다.
 */
export function expandAuthorMacros(
  text: string,
  names: { userName: string; charName: string | null },
): string {
  // 바꿀 글을 함수로 돌려준다 — 문자열로 넘기면 이름 속 `$&` 같은 글자가 치환 패턴으로 읽힌다.
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
