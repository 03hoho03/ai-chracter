import { describe, expect, it } from "vitest";

import { insertNarrationMarker } from "./insertNarrationMarker";

// 캐럿·선택은 `|` 와 `[ ]` 로 적는다 — 입력 `"안녕[하세]요"` 는 "하세" 를 고른 상태, `"안녕|"` 은 캐럿만 있는 상태.
function parse(marked: string) {
  const caret = marked.indexOf("|");
  if (caret >= 0) {
    return { text: marked.replace("|", ""), selectionStart: caret, selectionEnd: caret };
  }
  const start = marked.indexOf("[");
  const end = marked.indexOf("]") - 1;
  return { text: marked.replace("[", "").replace("]", ""), selectionStart: start, selectionEnd: end };
}

function format({ text, selectionStart, selectionEnd }: ReturnType<typeof parse>): string {
  if (selectionStart === selectionEnd) return `${text.slice(0, selectionStart)}|${text.slice(selectionStart)}`;
  return `${text.slice(0, selectionStart)}[${text.slice(selectionStart, selectionEnd)}]${text.slice(selectionEnd)}`;
}

describe("insertNarrationMarker", () => {
  it.each([
    ["빈 입력창이면 별표 한 쌍을 넣고 캐럿을 그 사이에 둔다", "|", "*|*"],
    ["글 끝의 캐럿에서도 같다", "안녕|", "안녕*|*"],
    ["글 가운데의 캐럿에서도 같다", "안녕| 나야", "안녕*|* 나야"],
    ["고른 글을 별표로 감싸고 캐럿을 닫는 별표 뒤로 옮긴다", "[고개를 끄덕였다] 그래", "*고개를 끄덕였다*| 그래"],
    ["여러 줄을 골라도 통째로 감싼다", "[문을 열었다\n바람이 분다]", "*문을 열었다\n바람이 분다*|"],
    [
      "고른 범위 양끝의 공백은 별표 밖에 남긴다 — 별표가 공백에 붙으면 지문으로 읽히지 않는다",
      "그래[ 끄덕였다 ]나야",
      "그래 *끄덕였다*| 나야",
    ],
    ["공백만 골랐으면 감싸지 않고 고른 범위 끝에 한 쌍을 넣는다", "그래[  ]나야", "그래  *|*나야"],
    ["단축어 입력(`/`로 시작)은 앞에 별표가 붙지 않아 그대로 단축어로 남는다", "/인사|", "/인사*|*"],
    // 이미 지문인 글을 다시 누르면 별표를 벗긴다(토글). 벗긴 뒤에는 그 글을 고른 채로 두어 한 번 더 누르면 되감싼다.
    ["별표까지 통째로 고른 지문은 별표를 벗긴다", "[*끄덕였다*] 그래", "[끄덕였다] 그래"],
    ["별표 안쪽만 고른 지문도 별표를 벗긴다", "*[끄덕였다]* 그래", "[끄덕였다] 그래"],
    ["고른 범위 양끝 공백 안쪽의 지문도 벗긴다", "그래[ *끄덕* ]나야", "그래 [끄덕] 나야"],
    ["굵게(`**`)로 감싼 글은 벗기지 않고 지문으로 한 겹 더 감싼다", "[**굵게**]", "***굵게***|"],
    ["굵게 안쪽만 골라도 벗기지 않는다", "**[굵게]**", "***굵게*|**"],
    ["바깥 한쪽에만 별표가 있으면 벗기지 않고 감싼다", "*[가] 나", "**가*| 나"],
    ["바깥 한쪽이 굵게 표지(`**`)면 벗기지 않고 감싼다", "**[가]* 나", "***가*|* 나"],
    ["고른 글의 한쪽 끝만 굵게 표지면 지문이 아니라 감싼다", "[**가*]", "***가**|"],
    ["바깥 오른쪽이 굵게 표지(`**`)여도 벗기지 않고 감싼다", "*[가]** 나", "**가*|** 나"],
    ["고른 글의 오른쪽 끝만 굵게 표지여도 감싼다", "[*가**]", "**가***|"],
    // 별표 짝은 빈 줄(문단 경계)을 넘지 못한다 — 한 쌍으로 감싸면 양끝 별표가 짝을 잃는다. 문단마다 따로 감싼다.
    ["빈 줄을 넘는 선택은 문단마다 따로 감싼다", "[문을 열었다\n\n바람이 분다]", "*문을 열었다*\n\n*바람이 분다*|"],
    ["공백만 있는 문단은 건너뛴다", "[가\n\n  \n\n나]", "*가*\n\n  \n\n*나*|"],
    [
      "이미 지문인 문단은 그대로 두고 나머지만 감싼다 — 다시 감싸면 굵게가 된다",
      "[*문을 열었다*\n\n바람이 분다]",
      "*문을 열었다*\n\n*바람이 분다*|",
    ],
    ["모든 문단이 이미 지문이면 전부 벗긴다", "[*문을 열었다*\n\n*바람이 분다*]", "[문을 열었다\n\n바람이 분다]"],
  ])("%s", (_name, before, after) => {
    expect(format(insertNarrationMarker(parse(before)))).toBe(after);
  });

  it("거꾸로 들어온 선택 범위(end < start)도 앞뒤를 바로잡아 감싼다", () => {
    expect(insertNarrationMarker({ text: "가나다", selectionStart: 3, selectionEnd: 0 })).toEqual({
      text: "*가나다*",
      selectionStart: 5,
      selectionEnd: 5,
    });
  });
});
