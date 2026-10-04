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
 * - 고치는 쌍(받침 있을 때/없을 때): 조사 `은/는·이/가·을/를·과/와·아/야·이랑/랑·으로/로`, 서술격
 *   `이에요/예요·이다/다·이나/나·이며/며·이고/고·이라고/라고·이라서/라서·이야/야`. 이 밖의 말은 손대지 않는다.
 * - 매크로 바로 뒤(또는 닫는 따옴표·괄호 한 글자 `'’"”」』)` 뒤 — `'{{user}}'가`)에 쌍 중 하나가 있고 그 뒤가 한글
 *   음절이 아니거나 글 끝일 때만, 이름의 끝 글자 받침에 맞는 쪽으로 바꾼다. 작가가 어느 쪽을 썼든 바꾼다(이름은 읽는
 *   사람마다 다르다). 뒤가 한글 음절이면 낱말의 일부일 수 있어(`{{user}}가방`) 그대로 둔다.
 * - 같은 경계 검사 덕에 긴 쌍과 그 앞부분이 겹쳐도 하나만 맞는다 — `{{user}}이고` 의 `이` 는 뒤의 `고` 가 한글이라
 *   주격으로 읽히지 않는다. 그래서 대안의 순서가 결과를 바꾸지 않는다.
 * - `야` 는 두 쌍에 다 있다. 작가가 쓴 `야` 는 부르는 말(`아/야`)로 읽고, 서술격은 `이야` 로 써야 고친다
 *   (`그건 {{user}}이야` → 지훈이야·민수야).
 * - ㄹ 받침 뒤에는 `으로` 가 아니라 `로` 가 맞다. 다른 쌍은 받침 유무만 본다.
 * - 이름 끝 글자가 한글 음절이 아니면(`Alex`, `R2`) 받침을 알 수 없어 작가가 쓴 조사를 그대로 둔다.
 */

/** 대화 프로필도 작품 기본 이름도 없을 때 쓰는 이름. */
export const FALLBACK_USER_NAME = "당신";

/** `{{user}}`·`{{char}}` 자리에 넣을 이름. `charName` 이 null 이면 `{{char}}` 를 글자 그대로 둔다. */
export type AuthorMacroNames = { userName: string; charName: string | null };

type AuthorMacroNameSource = {
  /** 이 화면에서 쓸 대화 프로필 이름 — 방 화면은 방의 프로필, 방 없는 화면은 보는 사람의 기본 프로필. 없으면 null. */
  personaName: string | null | undefined;
  /** 작가가 작품에 적어 둔 기본 이름. 비어 있으면 대체어를 쓴다. */
  defaultUserName: string | null | undefined;
  contentType: "character" | "story";
  /** 작품 이름 — 캐릭터 작품에서만 `{{char}}` 가 된다. */
  contentName: string | null | undefined;
};

/**
 * 화면에서 작가 글의 매크로를 무엇으로 바꿀지 정하는 유일한 규칙. 사용자 이름은 대화 프로필 이름 → 작품 기본 이름 →
 * `FALLBACK_USER_NAME` 순이다(서버 `resolve_user_name` 과 같은 순서 — 모델이 부른 이름과 화면의 이름이 같아야 한다).
 * `{{char}}` 는 캐릭터 작품에서만 작품 이름이다 — 스토리에는 가리킬 한 사람이 없다.
 * 화면마다 다른 것은 어느 프로필 이름을 넘기느냐뿐이고, 그 선택은 호출부가 한다.
 */
export function resolveAuthorMacroNames(source: AuthorMacroNameSource): AuthorMacroNames {
  return {
    userName: source.personaName || source.defaultUserName || FALLBACK_USER_NAME,
    charName: source.contentType === "character" ? source.contentName || null : null,
  };
}

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
// 매크로와 조사 사이에 올 수 있는 닫는 따옴표·괄호 한 글자.
const CLOSING_MARKS = `'’"”」』)`;
const PARTICLE_ALTERNATION = [...PARTICLE_BY_FORM.keys()].join("|");
const MACRO = new RegExp(
  String.raw`\{\{[ \t]*([A-Za-z]+)[ \t]*\}\}(?:([${CLOSING_MARKS}])?(${PARTICLE_ALTERNATION})(?![가-힣]))?`,
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
  names: AuthorMacroNames,
): string {
  // 바꿀 글을 함수로 돌려준다 — 문자열로 넘기면 이름 속 `$&` 같은 글자가 치환 패턴으로 읽힌다.
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
      return written === undefined
        ? name
        : name + (mark ?? "") + particleFor(name, written);
    },
  );
}

// 이름은 작가 글 한가운데에 끼어든다. 채팅 렌더러(`entities/chat-room/lib/chatMarkdown.ts`)에서 표기가 되는 문자가
// 이름에 있으면 이름 밖의 작가 글까지 지문·코드·목록·인용으로 바뀐다. 서버(`apps/api/src/api/content/author_macros.py`
// 의 `user_name_error`)가 저장을 막는 규칙과 같다 — 폼이 먼저 막아 서버 422 가 일반 오류 문구로 끝나지 않게 한다.
// - 콜론·줄바꿈: 대화 기록의 화자 라벨과 생성 중단 문자열이 반각 `:` 와 줄을 본다(전각 `：` 는 막지 않는다).
// - `*` 는 지문·굵게, `` ` `` 는 코드, `\` 는 뒤 글자를 이스케이프한다 — 어디에 있든 표기다.
// - `&#42;`·`&ast;` 같은 문자 참조는 파서가 `*` 로 풀고, 렌더러가 그 별표를 다시 지문으로 짝짓는다.
// - 인용·목록 표시와 `~~~` 는 줄 머리에서만 표기라 그것으로 시작하는 이름만 막는다(`김-민`·`별~`·`>_<` 는 글자다).
//   `>`·목록 표시는 뒤가 공백이거나 이름 끝일 때 표시다 — 이름 혼자 한 줄이면 빈 목록·빈 인용이 된다.
// - `---`·`___` 만으로 된 이름은 혼자 한 줄이면 구분선이 된다.
const FORBIDDEN_LABEL_CHARACTERS = /[:\n\r]/;
const FORBIDDEN_NOTATION_CHARACTERS = /[*`\\]/;
const CHARACTER_REFERENCE = /&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);/;
const LINE_START_MARKER = /^(?:(?:>|[-+]|[0-9]{1,9}[.)])(?=\s|$)|~~~)/;
const THEMATIC_BREAK = /^(?:(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$/;

/** 대화 프로필 이름이 `{{user}}` 자리에 들어갈 수 없는 이유. 들어갈 수 있으면 null. 앞뒤 공백을 걷은 이름을 받는다. */
export function userNameError(name: string): string | null {
  if (FORBIDDEN_LABEL_CHARACTERS.test(name))
    return "이름에는 콜론(:)이나 줄바꿈을 쓸 수 없어요";
  if (FORBIDDEN_NOTATION_CHARACTERS.test(name) || CHARACTER_REFERENCE.test(name))
    return "이름에는 별표(*)·백틱(`)·역슬래시(\\)나 &와 ;로 둘러싼 표기를 쓸 수 없어요";
  if (LINE_START_MARKER.test(name) || THEMATIC_BREAK.test(name))
    return "이름을 >, -, +, 1. 같은 인용·목록 표시나 ~~~ 로 시작하거나 ---·___ 로만 지을 수 없어요";
  return null;
}

/**
 * 작품 기본 이름이 `{{user}}` 자리에 들어갈 수 없는 이유. 빈 값은 대체어를 쓴다는 뜻이라 허용한다.
 * 프로필 이름 규칙에 중괄호를 더 막는다 — 작가가 이름 칸에 매크로나 이미지 태그를 숨겨 넣지 못하게.
 */
export function defaultUserNameError(name: string): string | null {
  if (name.includes("{") || name.includes("}"))
    return "기본 이름에는 중괄호({, })를 쓸 수 없어요";
  return userNameError(name);
}
