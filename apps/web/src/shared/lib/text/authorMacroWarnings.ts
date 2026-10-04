/**
 * 빌더가 작가에게 알릴 매크로 실수를 찾는 순수 함수. 치환 규칙(`authorMacros.ts`)은 이 글들을 고치지 않고 글자 그대로
 * 두므로, 작가가 화면에서 알아채기 전에 입력칸 아래에서 먼저 알린다. 발행은 막지 않는다.
 */

// 중괄호 겹 수와 상관없이 `user`·`char` 를 감싼 모양을 모두 잡고, 두 겹으로 정확히 여닫힌 것만 정상으로 본다.
// 이름 뒤에 영문이 이어지면(`{username}`) 다른 낱말이라 잡지 않는다. 중괄호 안쪽 앞뒤 공백·탭은 치환 규칙처럼 허용한다.
const BRACED_MACRO = /(\{+)[ \t]*(?:user|char)(?![A-Za-z])[ \t]*(\}*)/gi;
// 다른 서비스의 옛 표기. 이 서비스는 읽지 않는다.
const ANGLE_MACRO = /<[ \t]*(?:user|char)[ \t]*>/gi;
const CHAR_MACRO = /\{\{[ \t]*char[ \t]*\}\}/i;
const USER_MACRO = /\{\{[ \t]*user[ \t]*\}\}/i;

/**
 * 이름으로 바뀌지 않는 매크로 오타(`{user}`·`{{user}`·`{{{user}}}`·`<USER>` 등)를 글에 나온 모양 그대로, 중복 없이
 * 돌려준다. `{{user}}`·`{{ char }}`·`{{USER}}` 는 바뀌므로 오타가 아니다.
 */
export function findAuthorMacroTypos(text: string): string[] {
  const typos: string[] = [];
  for (const match of text.matchAll(BRACED_MACRO)) {
    const [whole, open = "", close = ""] = match;
    if (open.length !== 2 || close.length !== 2) typos.push(whole.trim());
  }
  for (const match of text.matchAll(ANGLE_MACRO)) typos.push(match[0]);
  return [...new Set(typos)];
}

/** 이름으로 바뀌는 `{{char}}` 가 글에 있는가. 스토리에는 가리킬 한 사람이 없어 바뀌지 않는다. */
export function hasCharMacro(text: string): boolean {
  return CHAR_MACRO.test(text);
}

/** 이름으로 바뀌는 `{{user}}` 가 글에 있는가. 미디어 북 인물·장면 이름은 이미지 표기의 열쇠라 바꾸지 않는다. */
export function hasUserMacro(text: string): boolean {
  return USER_MACRO.test(text);
}
