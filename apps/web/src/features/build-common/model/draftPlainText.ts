import type { BuilderTab } from "@/entities/content";

import { BUILDER_STEP_LABELS, tabsInStepOrder, type TabStepTable } from "./builderSteps";
import { matchTabForPath } from "./fieldErrorPaths";
import { fieldLabelForPath, type FieldLabelTable } from "./publishIssues";

type DraftPlainTextOptions<TTabId extends string> = {
  /** 빌더의 탭 배열. 절 순서는 이 배열이 아니라 묶음 순서다. */
  tabs: readonly (BuilderTab & { readonly id: TTabId })[];
  steps: TabStepTable<TTabId>;
  /** 칸 라벨 표. 이 표에 키가 있는 칸만 싣는다 — 화면에 칸이 없는 값(id·표시용 그림 주소)은 표에 없다. */
  labels: FieldLabelTable;
  /** 표에 있지만 값이 고르는 항목의 원시값(장르 id·타겟 키)이라 글로 옮겨도 뜻이 없는 칸. 배열 위치는 `*` 로 쓴다. */
  choiceFields: ReadonlySet<string>;
};

type Line = { path: string; text: string };

const INDEX_SEGMENT = /^\d+$/;
/** 그림 칸의 자산 id(`assetId`, 미디어 북 칸의 `imageAssetId`). 그림은 글로 옮길 수 없어 장수만 센다. */
const ASSET_ID_KEY = /assetId$/i;

function wildcardKey(segments: readonly string[]): string {
  return segments.map((segment) => (INDEX_SEGMENT.test(segment) ? "*" : segment)).join(".");
}

/**
 * 폼 값의 글 칸을 칸 이름을 붙인 평문으로 옮긴다 — 저장이 실패하거나 연결이 끊긴 동안 작가가 쓴 글을 다른 곳에 붙여 둘 수 있게.
 * 순수 함수.
 *
 * 빌더마다 직렬화기를 따로 두지 않고 값을 한 번 순회한다. 글(또는 글 목록)이면서 라벨 표에 키가 있는 칸만 싣고 빈 칸은 뺀다. 칸
 * 이름은 발행 전 확인 목록과 같은 `fieldLabelForPath`("1번째 시작설정 프롤로그"), 절은 그 칸이 걸린 탭(`matchTabForPath`)이다.
 * 절은 묶음 순서로, 절 안은 폼 값 순서로 선다. 그림은 장수 한 줄로만 남긴다. 실을 것이 하나도 없으면 빈 글이다.
 */
export function draftPlainText<TTabId extends string>(values: unknown, options: DraftPlainTextOptions<TTabId>): string {
  const lines: Line[] = [];
  let imageCount = 0;

  function addLine(segments: readonly string[], text: string) {
    const path = segments.join(".");
    const label = fieldLabelForPath(path, options.labels);
    if (label !== undefined) lines.push({ path, text: `${label}: ${text}` });
  }

  function isTextField(segments: readonly string[]): boolean {
    const key = wildcardKey(segments);
    return options.labels[key] !== undefined && !options.choiceFields.has(key);
  }

  function visit(node: unknown, segments: string[]) {
    if (typeof node === "string") {
      const key = segments[segments.length - 1] ?? "";
      if (ASSET_ID_KEY.test(key)) {
        if (node !== "") imageCount += 1;
        return;
      }
      if (node.trim() !== "" && isTextField(segments)) addLine(segments, node);
      return;
    }
    if (Array.isArray(node)) {
      if (node.length > 0 && node.every((item) => typeof item === "string")) {
        const items = node.filter((item) => item.trim() !== "");
        if (items.length > 0 && isTextField(segments)) addLine(segments, items.join(", "));
        return;
      }
      node.forEach((item, index) => visit(item, [...segments, String(index)]));
      return;
    }
    if (typeof node === "object" && node !== null) {
      for (const [key, value] of Object.entries(node)) visit(value, [...segments, key]);
    }
  }

  visit(values, []);

  const sections: string[] = [];
  for (const tab of tabsInStepOrder(options.tabs, options.steps)) {
    const tabLines = lines.filter((line) => matchTabForPath(line.path, options.tabs) === tab.id);
    if (tabLines.length === 0) continue;
    const heading = `[${BUILDER_STEP_LABELS[options.steps[tab.id]]} › ${tab.label}]`;
    sections.push([heading, ...tabLines.map((line) => line.text)].join("\n"));
  }
  if (imageCount > 0) sections.push(`(그림 ${imageCount}장은 복사에서 빠져요)`);
  return sections.join("\n\n");
}
