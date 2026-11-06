import type { ClaudeModelAxis } from "./credential";

/** 모델 축 이름. 버전 숫자는 넣지 않는다 — 실제 id 는 목록 응답의 `modelIds` 가 보인다. 키 순서가 화면의 축 순서이고 서버의 축
 * 순서(확인 행·`runtimeAxes` 를 싣는 순서)와 같다. */
export const AXIS_LABELS = {
  opus: "Opus",
  sonnet: "Sonnet",
  haiku_writer: "Haiku 글쓰기",
  haiku: "Haiku 판정",
} as const satisfies Record<ClaudeModelAxis, string>;

/** 서버가 오류 본문(`pool-uncovered` 의 `axes`)이나 `modelIds` 키로 싣는 축 이름을 좁힌다 — 그 자리는 생성 타입이 없다. */
export function isClaudeModelAxis(value: unknown): value is ClaudeModelAxis {
  return typeof value === "string" && Object.hasOwn(AXIS_LABELS, value);
}

/** 화면이 축을 훑는 순서. 이름표의 키에서 도출해 목록과 유니언이 갈리지 않는다(이름표가 유니언 전체를 덮는지는 `satisfies` 가 본다). */
export const CLAUDE_MODEL_AXES: readonly ClaudeModelAxis[] = Object.keys(AXIS_LABELS).filter(isClaudeModelAxis);

/** "Opus·Sonnet" 처럼 축 이름을 가운뎃점으로 잇는다. */
export function axisNames(axes: readonly ClaudeModelAxis[]): string {
  return axes.map((axis) => AXIS_LABELS[axis]).join("·");
}
