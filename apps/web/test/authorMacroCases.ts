// 작가 글 매크로 치환 입력 표 — 서버 테스트 `apps/api/tests/test_author_macros.py` 와 함께 읽는 JSON 하나
// (`apps/api/tests/fixtures/author_macro_cases.json`)를 테스트가 쓰기 좋은 모양으로 편다. 프롬프트는 서버 구현으로,
// 화면은 웹 구현으로 바뀌므로 같은 표로 양쪽을 시험한다. 행은 JSON 에만 더한다.
// 도메인 픽스처라 shared 에 둘 수 없고, 앞으로 화면 치환 테스트가 여러 레이어에서 이 표를 읽을 수 있어 FSD 레이어 밖인
// `src/` 바깥에 둔다(미디어 북 태그 표와 같은 자리).

type AuthorMacroCasesFile = {
  expand: {
    id: string;
    text: string;
    userName: string;
    charName: string | null;
    expected: string;
  }[];
};

// 표가 앱 밖(`apps/api`)에 있어 레이어 alias 로 닿지 않는다. 글롭은 파일 하나만 맞춘다.
const CASE_FILES = import.meta.glob<AuthorMacroCasesFile>(
  "../../api/tests/fixtures/author_macro_cases.json",
  {
    import: "default",
    eager: true,
  },
);

/** [행 이름, 입력, 사용자 이름, 캐릭터 이름(스토리면 null), 기대 글] */
export type AuthorMacroCase = [string, string, string, string | null, string];

/** 표를 읽어 편다. */
export function loadAuthorMacroCases(): AuthorMacroCase[] {
  const [cases] = Object.values(CASE_FILES);
  if (cases === undefined)
    throw new Error("author_macro_cases.json 을 찾지 못했다");
  return cases.expand.map((row) => [
    row.id,
    row.text,
    row.userName,
    row.charName,
    row.expected,
  ]);
}
