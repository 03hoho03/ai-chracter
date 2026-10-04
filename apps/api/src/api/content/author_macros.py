"""작가 글 속 `{{user}}`·`{{char}}` 를 이름으로 바꾸는 순수 함수와, 그 자리에 들어갈 이름의 금지 문자 규칙.

작가 글은 원문 그대로 저장하고 쓰는 순간 바꾼다. 웹(`apps/web/src/shared/lib/text/authorMacros.ts`)도 같은
규칙으로 화면 글을 바꾸므로 같은 입력 표로 양쪽을 시험한다 — 갈라지면 모델이 부른 이름과 화면의 이름이 다르다.

문법
- 이중 중괄호 안의 `user`·`char`, 대소문자 무시. 중괄호 안쪽 앞뒤의 공백·탭은 허용한다(줄바꿈은 아니다) —
  `{{ user }}` 를 글자로 남길 이유가 없고, 이미지 태그도 이름 앞뒤 공백을 무시한다. 글자는 ASCII 로만 비교한다
  (유니코드 대소문자 접기는 `ſ`→`s` 처럼 언어마다 결과가 달라 웹 구현과 갈라진다).
- 한 번에 훑고 끝난다. 바꿔 넣은 이름 속의 `{{char}}`·`{{img::…}}` 는 다시 읽지 않는다. 이미지 태그
  (`{{img::…}}`)는 이 문법에 맞지 않아 손대지 않는다 — 이름이 태그가 되지 않게, 호출부는 태그 처리를 먼저 하고
  이 함수를 나중에 부른다.
- 스토리(`char_name` 이 None)에는 `{{char}}` 가 가리킬 한 사람이 없다. 몰래 지우면 작가가 모르므로 글자 그대로 둔다.

조사 보정
- 매크로 바로 뒤에 `은/는·이/가·을/를·과/와·아/야·이랑/랑·으로/로` 중 하나가 있고 그 뒤가 한글 음절이 아니거나
  글 끝일 때만, 이름의 끝 글자 받침에 맞는 쪽으로 바꾼다. 작가가 어느 쪽을 썼든 바꾼다(이름은 읽는 사람마다 다르다).
  뒤가 한글 음절이면 조사가 아니라 낱말의 일부일 수 있어(`{{user}}가방`) 그대로 둔다. 같은 경계 검사 덕에
  `이랑` 이 `이` 로 읽히는 일도 없다(`이` 뒤의 `랑` 이 한글이라 짧은 쪽은 맞지 않는다).
- ㄹ 받침 뒤에는 `으로` 가 아니라 `로` 가 맞다.
- 이름 끝 글자가 한글 음절이 아니면(`Alex`, `R2`) 받침을 알 수 없으므로 작가가 쓴 조사를 그대로 둔다.
"""

import re

# 대화 프로필도 작품 기본 이름도 없을 때 쓰는 이름. 이름 고르기는 호출부가 하고, 이 값만 여기서 정한다.
FALLBACK_USER_NAME = "당신"

# 받침 있는 이름 뒤의 형태 → 받침 없는 이름 뒤의 형태.
_PARTICLE_PAIRS = {"은": "는", "이": "가", "을": "를", "과": "와", "아": "야", "이랑": "랑", "으로": "로"}
_PARTICLE_BY_FORM = {form: pair for pair in _PARTICLE_PAIRS.items() for form in pair}
_PARTICLE_ALTERNATION = "|".join(_PARTICLE_BY_FORM)
_MACRO = re.compile(r"\{\{[ \t]*([A-Za-z]+)[ \t]*\}\}(?:(" + _PARTICLE_ALTERNATION + r")(?![가-힣]))?")

_HANGUL_FIRST = ord("가")
_HANGUL_LAST = ord("힣")
_RIEUL_FINAL = 8  # 한글 음절의 종성 번호에서 ㄹ


def resolve_user_name(persona_name: str | None, default_user_name: str) -> str:
    """`{{user}}` 자리에 넣을 이름을 고른다 — 대화 프로필 이름 → 작품 기본 이름 → `FALLBACK_USER_NAME`."""
    return persona_name or default_user_name or FALLBACK_USER_NAME


def _final_consonant(name: str) -> int | None:
    """이름 끝 글자의 종성 번호(0 = 받침 없음). 끝 글자가 한글 음절이 아니면 None."""
    if not name:
        return None
    code = ord(name[-1])
    if not _HANGUL_FIRST <= code <= _HANGUL_LAST:
        return None
    return (code - _HANGUL_FIRST) % 28


def _particle_for(name: str, written: str) -> str:
    final = _final_consonant(name)
    if final is None:
        return written
    with_final, without_final = _PARTICLE_BY_FORM[written]
    if final == 0 or (final == _RIEUL_FINAL and with_final == "으로"):
        return without_final
    return with_final


def expand_author_macros(text: str, *, user_name: str, char_name: str | None) -> str:
    """작가 글의 `{{user}}` 를 `user_name` 으로, `{{char}}` 를 `char_name` 으로 바꾸고 바로 뒤 조사를 맞춘다.

    `user_name` 은 호출부가 이미 고른 이름이다(대화 프로필 → 작품 기본 이름 → `FALLBACK_USER_NAME`).
    `char_name` 이 None 이면 스토리라 `{{char}}` 를 글자 그대로 둔다."""
    names = {"user": user_name, "char": char_name}

    def substitute(match: re.Match[str]) -> str:
        name = names.get(match.group(1).lower())
        if name is None:
            return match.group(0)
        written = match.group(2)
        return name if written is None else name + _particle_for(name, written)

    return _MACRO.sub(substitute, text)


# 이름은 작가 글 한가운데에 끼어든다. 채팅 렌더러(`apps/web/src/entities/chat-room/lib/chatMarkdown.ts`)에서 표기가
# 되는 문자가 이름에 있으면 이름 밖의 작가 글까지 지문·코드·목록·인용으로 바뀐다.
# - 콜론·줄바꿈: 대화 기록의 화자 라벨과 stop sequence 가 반각 `:` 와 줄을 본다(전각 `：` 는 막지 않는다).
# - `*` 는 지문·굵게, `` ` `` 는 코드, `\` 는 뒤 글자를 이스케이프한다 — 어디에 있든 표기다.
# - `&#42;`·`&ast;` 같은 문자 참조는 파서가 `*` 로 풀고, 렌더러가 그 별표를 다시 지문으로 짝짓는다.
# - 인용·목록 표시와 `~~~` 는 줄 머리에서만 표기라, 그것으로 시작하는 이름만 막는다(`김-민`·`별~`·`>_<` 는 글자다).
#   `>`·목록 표시는 뒤가 공백이거나 이름 끝일 때 표시다 — 이름 혼자 한 줄이면 빈 목록·빈 인용이 된다.
# - `---`·`___` 만으로 된 이름은 혼자 한 줄이면 구분선이 된다.
# `_`·`#`·`[`·`<` 는 렌더러가 표기로 읽지 않으므로 막지 않는다.
_FORBIDDEN_LABEL_CHARACTERS = (":", "\n", "\r")
_FORBIDDEN_NOTATION_CHARACTERS = ("*", "`", "\\")
_CHARACTER_REFERENCE = re.compile(r"&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
_LINE_START_MARKER = re.compile(r"(?:(?:>|[-+]|[0-9]{1,9}[.)])(?=\s|$)|~~~)")
_THEMATIC_BREAK = re.compile(r"(?:-[ \t]*){3,}|(?:_[ \t]*){3,}")


def user_name_error(name: str) -> str | None:
    """대화 프로필 이름이 `{{user}}` 자리에 들어갈 수 없는 이유. 들어갈 수 있으면 None."""
    if any(character in name for character in _FORBIDDEN_LABEL_CHARACTERS):
        return "이름에는 콜론(:)이나 줄바꿈을 쓸 수 없어요."
    if any(character in name for character in _FORBIDDEN_NOTATION_CHARACTERS) or _CHARACTER_REFERENCE.search(name):
        return "이름에는 별표(*)·백틱(`)·역슬래시(\\)나 &…; 형태의 문자를 쓸 수 없어요."
    if _LINE_START_MARKER.match(name) or _THEMATIC_BREAK.fullmatch(name):
        return "이름을 >, -, +, 1. 같은 인용·목록 표시나 ~~~ 로 시작하거나 ---·___ 로만 지을 수 없어요."
    return None


def default_user_name_error(name: str) -> str | None:
    """작품 기본 이름이 `{{user}}` 자리에 들어갈 수 없는 이유. 빈 값은 대체어를 쓴다는 뜻이라 허용한다.

    프로필 이름 규칙에 중괄호를 더 막는다 — 작가가 이름 칸에 매크로나 이미지 태그를 숨겨 넣지 못하게."""
    if "{" in name or "}" in name:
        return "기본 이름에는 중괄호({, })를 쓸 수 없어요."
    return user_name_error(name)
