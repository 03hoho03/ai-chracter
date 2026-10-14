import { get, set, type FieldErrors, type FieldValues } from "react-hook-form";

import type { BuilderTab } from "@/entities/content";

import { matchTabForPath } from "./fieldErrorPaths";

/** 발행이 막혔을 때 토스트가 하는 말. 칸 이름은 폼 열 맨 위 목록이 나열하므로 토스트는 그 목록만 가리킨다. 클라 검증 실패와
 * 서버 400 이 같은 문장이다. */
export const PUBLISH_ISSUES_TOAST = "발행하려면 위 목록의 항목을 확인해 주세요.";

/** 칸 라벨 표의 한 줄. 키는 폼 경로이고 배열 위치는 `*` 로 쓴다(`startingSetups.*.prologue`). */
export type FieldLabelEntry = {
  label: string;
  /** 목록 키에만 둔다 — 그 목록의 항목 하나를 부르는 이름이 목록 라벨과 다를 때(키워드북의 항목은 "노트"). 없으면 `label`. */
  item?: string;
};

export type FieldLabelTable = Readonly<Record<string, FieldLabelEntry | undefined>>;

const INDEX_SEGMENT = /^\d+$/;

function isIndex(segment: string): boolean {
  return INDEX_SEGMENT.test(segment);
}

function wildcardKey(segments: readonly string[]): string {
  return segments.map((segment) => (isIndex(segment) ? "*" : segment)).join(".");
}

/** 경로 조각의 배열 위치마다 "N번째 {항목 이름}" 을 만든다. 항목 이름을 모르는 배열이 끼어 있으면 `undefined`. */
function ordinals(segments: readonly string[], labels: FieldLabelTable): string[] | undefined {
  const result: string[] = [];
  for (let index = 0; index < segments.length; index++) {
    const segment = segments[index];
    if (segment === undefined || !isIndex(segment)) continue;
    const list = labels[wildcardKey(segments.slice(0, index))];
    if (list === undefined) return undefined;
    result.push(`${Number(segment) + 1}번째 ${list.item ?? list.label}`);
  }
  return result;
}

/**
 * 오류 경로의 칸 이름. 배열 위치는 "N번째 {항목}" 으로 앞에 붙는다(`startingSetups.0.prologue` → "1번째 시작설정 프롤로그"). 순수 함수.
 *
 * 표에 그 경로가 없으면 가장 가까운 조상으로 올라간다 — 라벨이 없는 하위 구조(규칙 줄의 스탯 칸, 중복 id 처럼 화면에 칸이 없는
 * 자리)의 오류는 그것을 품은 칸이나 항목의 이름으로 부른다. 항목 자리(`mediaBook.cells.3`)는 "4번째 칸" 처럼 항목 이름만 남는다.
 * 조상 어디에도 이름이 없으면 `undefined`.
 */
export function fieldLabelForPath(path: string, labels: FieldLabelTable): string | undefined {
  const segments = path.split(".");
  for (let length = segments.length; length > 0; length--) {
    const head = segments.slice(0, length);
    const last = head[length - 1] ?? "";
    if (isIndex(last)) {
      if (labels[wildcardKey(head.slice(0, -1))] === undefined) continue;
      const items = ordinals(head, labels);
      if (items !== undefined) return items.join(" ");
      continue;
    }
    const entry = labels[wildcardKey(head)];
    if (entry === undefined) continue;
    const items = ordinals(head.slice(0, -1), labels);
    if (items !== undefined) return [...items, entry.label].join(" ");
  }
  return undefined;
}

export type PublishIssueRow = {
  /** 오류가 걸린 폼 경로 — 누르면 이 칸으로 간다. */
  path: string;
  tabId: string;
  /** "{탭 이름} · {칸 이름}". 칸 이름이 탭 이름으로 시작하면 칸 이름만(같은 말을 두 번 읽지 않게). */
  label: string;
};

/**
 * 오류 경로들을 발행 전 확인 목록의 줄로 만든다. 순수 함수.
 *
 * 줄은 탭 순서(화면에 보이는 순서)를 따르고 같은 탭 안에서는 받은 순서다 — `flattenFieldErrorPaths` 가 스키마 선언 순서로 주므로
 * 첫 오류로 가는 이동과 같은 줄이 맨 위에 선다. 같은 경로나 같은 이름은 한 줄이다(한 칸의 중복 id 오류와 그 칸 자체의 오류처럼 이름이
 * 같은 줄은 같은 곳으로 가니 둘로 세지 않는다). 어느 탭에도 들지 않는 경로는 갈 곳이 없어 뺀다. 칸 이름을
 * 못 찾으면 탭 이름만 남긴다 — 영문 경로나 뜻 없는 대체 문구를 보이지 않는다. 칸 이름이 탭 이름으로 시작하면("1번째 상황별
 * 이미지 노출할 상황", "스탯 규칙(…)", 목록 자체의 오류라 칸 이름이 탭 이름인 경우 포함) 탭 이름을 앞에 다시 붙이지 않는다. 탭
 * 이름이 뒤에 나오는 칸("1번째 시작설정 2번째 스탯 최대값")은 앞의 탭 이름이 있어야 어느 탭인지 읽히므로 그대로 둔다.
 */
export function publishIssueRows(
  paths: readonly string[],
  tabs: readonly BuilderTab[],
  labelFor: (path: string) => string | undefined,
): PublishIssueRow[] {
  const seen = new Set<string>();
  const rows: (PublishIssueRow & { order: number })[] = [];
  for (const path of paths) {
    if (seen.has(path)) continue;
    seen.add(path);
    const tabId = matchTabForPath(path, tabs);
    const order = tabs.findIndex((tab) => tab.id === tabId);
    const tab = tabs[order];
    if (tab === undefined) continue;
    const label = rowLabel(tab.label, labelFor(path));
    if (rows.some((row) => row.label === label)) continue;
    rows.push({ path, tabId: tab.id, label, order });
  }
  // `sort` 는 안정 정렬이라 같은 탭 안에서는 받은 순서가 남는다.
  return rows.sort((a, b) => a.order - b.order).map(({ path, tabId, label }) => ({ path, tabId, label }));
}

function rowLabel(tabLabel: string, detail: string | undefined): string {
  if (detail === undefined) return tabLabel;
  return startsWithTab(detail, tabLabel) ? detail : `${tabLabel} · ${detail}`;
}

/** 칸 이름이 탭 이름으로 시작하는가 — 맨 앞 순번("1번째 ")은 건너뛰고 본다. 탭 이름 뒤는 끝·띄어쓰기·괄호·쉼표여야 한다
 * ("스토리 설정/정보" 처럼 낱말 일부로 시작하는 것은 치지 않는다). */
function startsWithTab(detail: string, tabLabel: string): boolean {
  const rest = detail.replace(/^\d+번째 /, "");
  if (!rest.startsWith(tabLabel)) return false;
  const after = rest[tabLabel.length];
  return after === undefined || /[\s(,]/.test(after);
}

/**
 * 채움 표시를 붙일 탭 — 필수 탭 가운데 지금 값의 발행 검사 오류(`issuePaths`, 클라 검사와 아직 남은 서버 거절을 합친 것)가 하나도
 * 걸리지 않은 탭. 순수 함수. 경로→탭은 오류 표시와 같은 `matchTabForPath` 라 같은 경로가 체크와 오류 표시에서 다른 탭으로 가지 않는다.
 */
export function completedTabIds(
  requiredTabIds: ReadonlySet<string>,
  issuePaths: readonly string[],
  tabs: readonly BuilderTab[],
): Set<string> {
  const blocked = new Set<string>();
  for (const path of issuePaths) {
    const tabId = matchTabForPath(path, tabs);
    if (tabId !== undefined) blocked.add(tabId);
  }
  return new Set([...requiredTabIds].filter((tabId) => !blocked.has(tabId)));
}

/** 서버 거절 하나와, 거절받을 때 그 자리에 있던 값. */
export type ServerIssue = {
  path: string;
  message: string;
  /** 목록 줄에 쓸 칸 이름. 서버 키가 목록 자리만 가리킬 때(스탯 범위 등) 그 뜻을 담는다. 없으면 칸 라벨 표에서 찾는다. */
  label?: string;
  snapshot: string;
};

/** 값 비교용 직렬화. 폼 값은 JSON 으로 옮겨지는 값뿐이라 문자열로 같으면 같은 값이다. */
export function valueSnapshot(values: unknown, path: string): string {
  return JSON.stringify(get(values, path)) ?? "undefined";
}

/**
 * 아직 유효한 서버 거절 — 거절받은 뒤 그 자리 값이 바뀌지 않은 것만 남긴다. 순수 함수.
 *
 * 서버 거절은 클라 검사로 다시 따질 수 없는 조건(다른 기기에서 고친 상태 등)이 섞여 있어 "고쳤는가"를 값이 바뀌었는지로 판정한다.
 * 목록 자리(`keywordNotes`) 거절은 그 아래 무엇이 바뀌어도 풀린다. 바뀐 값이 여전히 틀렸으면 클라 검사가 그 자리를 다시 잡는다.
 */
export function unchangedServerIssues(issues: readonly ServerIssue[], values: unknown): ServerIssue[] {
  return issues.filter((issue) => valueSnapshot(values, issue.path) === issue.snapshot);
}

/** 경로 목록을 `FieldErrors` 모양(잎마다 `type`)으로 세운다 — 오류 객체를 받는 첫 오류 이동·항목 펼치기를 경로 하나나 몇 개로
 * 부르려는 것이다. 순수 함수. */
export function errorsAtPaths<T extends FieldValues>(paths: readonly string[]): FieldErrors<T> {
  const errors: FieldErrors<T> = {};
  for (const path of paths) set(errors, path, { type: "publish", message: "" });
  return errors;
}
