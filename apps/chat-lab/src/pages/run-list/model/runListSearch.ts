/** 런 목록 주소의 검색 칸 — 고른 폴더와 고른 행. 주소에 실어 두면 런 상세에서 돌아왔을 때 보던 자리가 그대로 열린다. */
export type RunListSearch = {
  /** 런 루트 기준 폴더 경로. 없으면 전체. */
  folder?: string;
  /** 고른 행의 키(런 id, 그룹 행은 `group:` 뒤에 폴더 경로). */
  row?: string;
};

/**
 * 라우터가 넘기는 검색 칸을 좁힌다. 라우터는 값을 JSON 으로 먼저 읽어 보므로 숫자만으로 된 폴더 이름은 수로 올 수 있어 글로
 * 되돌린다. 그 밖의 모양은 버린다.
 */
export function parseRunListSearch(search: Record<string, unknown>): RunListSearch {
  return { folder: asText(search.folder), row: asText(search.row) };
}

function asText(value: unknown): string | undefined {
  if (typeof value === "string" && value !== "") return value;
  if (typeof value === "number") return String(value);
  return undefined;
}
