// 정규화·삭제 입력 표 — 서버 테스트 `apps/api/tests/test_media_tags.py` 와 함께 읽는 JSON 하나
// (`apps/api/tests/fixtures/media_tag_cases.json`)를 테스트가 쓰기 좋은 모양으로 편다. 빌더 미리보기의 첫 메시지는
// FE 구현으로, 실채팅의 첫 메시지는 서버 구현으로 정규화되므로 같은 표로 양쪽을 시험한다. 행은 JSON 에만 더한다.
// 테스트만 이 파일을 읽는다.
import type { MediaTagCell } from "./mediaTags";

type MediaTagCasesFile = {
  cells: MediaTagCell[];
  normalize: { id: string; text: string; expectedText: string; expectedCellIds: string[] }[];
  strip: { id: string; text: string; expected: string }[];
};

// 표가 앱 밖(`apps/api`)에 있어 레이어 alias 로 닿지 않는다. 글롭은 파일 하나만 맞춘다.
const CASE_FILES = import.meta.glob<MediaTagCasesFile>("../../../../../api/tests/fixtures/media_tag_cases.json", {
  import: "default",
  eager: true,
});

export type MediaTagCases = {
  cells: MediaTagCell[];
  minaClassroom: string;
  minaRooftop: string;
  /** [행 이름, 입력, 기대 글, 기대 칸 id 목록] */
  normalizeCases: [string, string, string, string[]][];
  /** [행 이름, 입력, 기대 글] */
  stripCases: [string, string, string][];
};

/** 표를 읽어 편다. */
export function loadMediaTagCases(): MediaTagCases {
  const [cases] = Object.values(CASE_FILES);
  if (cases === undefined) throw new Error("media_tag_cases.json 을 찾지 못했다");
  const cellIdOf = (person: string, scene: string): string => {
    const cell = cases.cells.find((item) => item.person === person && item.scene === scene);
    if (cell === undefined) throw new Error(`표에 ${person}/${scene} 칸이 없다`);
    return cell.cellId;
  };
  return {
    cells: cases.cells,
    minaClassroom: cellIdOf("민아", "교실"),
    minaRooftop: cellIdOf("민아", "옥상"),
    normalizeCases: cases.normalize.map((row) => [row.id, row.text, row.expectedText, row.expectedCellIds]),
    stripCases: cases.strip.map((row) => [row.id, row.text, row.expected]),
  };
}
