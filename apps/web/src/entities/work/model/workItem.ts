import type { components, operations } from "@ai-character-chat/api-types";

export type WorkListResponse = components["schemas"]["WorkListResponse"];
export type WorkItem = WorkListResponse["items"][number];
export type ContentWorkItem = components["schemas"]["ContentWorkItem"];
export type NovelWorkItem = components["schemas"]["NovelWorkItem"];
export type NovelWorkPublication = components["schemas"]["NovelWorkPublication"];

type MyWorksQueryParams = NonNullable<operations["list_my_works_me_works_get"]["parameters"]["query"]>;

/** `GET /me/works` 에 실어 보내는 조건. 축은 언제나 값이 있다(전체는 `all`) — 주소의 "축 없음"을 서버 값으로 바꾸는
 * 일은 화면 쪽에서 한 번만 한다. */
export type MyWorksParams = {
  type: NonNullable<MyWorksQueryParams["type"]>;
  status: NonNullable<MyWorksQueryParams["status"]>;
  /** 이 묶음에 든 작품만. 없으면 묶음과 무관한 전체 목록이다. */
  bundleId?: string;
  /** 정규화된 검색어(`normalizeMyWorksQuery`). 없으면 검색하지 않는다. */
  q: string | undefined;
};

export type WorkBundleSummary = components["schemas"]["WorkBundleSummary"];
export type WorkBundleListResponse = components["schemas"]["WorkBundleListResponse"];
/** 묶음에 넣고 빼는 단위의 종류 — 목록 행의 `kind` 와 같은 값이다. */
export type WorkBundleKind = WorkItem["kind"];
