import { koreanParticle } from "@/shared/lib/text/koreanParticle";

/** 모든 작품 절의 본문이 무엇을 그릴지. 목록은 서버가 조건을 걸어 주는 한 쿼리라 받은 행 수가 곧 조건의 결과다.
 *
 * 검색어를 바꾼 뒤 새 응답을 기다리는 동안은 이전 결과가 자리표시로 남는데, 그 자리표시가 0건이면 결론(빈 결과·아직
 * 없음)을 내지 않는다 — 새 응답이 오면 뒤집힐 수 있는 문장을 먼저 읽히지 않으려고. */
export type StudioBodyView = "nothingMade" | "awaiting" | "emptyResult" | "list";

export function resolveStudioBodyView({
  itemCount,
  hasCondition,
  isShowingPlaceholder,
}: {
  itemCount: number;
  /** 유형·상태·검색어 중 하나라도 걸렸는지. */
  hasCondition: boolean;
  isShowingPlaceholder: boolean;
}): StudioBodyView {
  if (itemCount > 0) return "list";
  if (isShowingPlaceholder) return "awaiting";
  return hasCondition ? "emptyResult" : "nothingMade";
}

export type StudioEmptyResult = { message: string; action: "clearQuery" | "resetAll" };

/** 조건에 맞는 작품이 0건일 때의 문장과 버튼 하나. 걸린 조건을 이름으로 적어 "작품이 하나도 없다"로 읽히지 않게 한다.
 * 검색어만 걸렸으면 사용자가 한 일이 찾기라 "찾은"이라 쓰고 검색어만 지운다. 필터가 걸렸으면 버튼 하나로 모두 푼다. */
export function resolveStudioEmptyResult({
  q,
  filterLabel,
}: {
  q: string | undefined;
  /** 걸린 유형·상태를 이름으로 적은 말(`캐릭터 · 초안`). 없으면 `undefined`. */
  filterLabel: string | undefined;
}): StudioEmptyResult {
  if (filterLabel === undefined && q !== undefined) {
    return { message: `${quote(q)}${roParticle(q)} 찾은 작품이 없어요.`, action: "clearQuery" };
  }
  const scope = [q === undefined ? undefined : quote(q), filterLabel === undefined ? undefined : quote(filterLabel)]
    .filter((part) => part !== undefined)
    .join(" · ");
  return { message: `${scope}에 해당하는 작품이 없어요.`, action: "resetAll" };
}

/** 조사는 검색어 끝 글자에 맞춘다(`‘목욕탕’으로`, `‘바다’로`). 끝이 한글이 아니면 받침을 알 수 없어 `(으)로`가 된다. */
function roParticle(q: string): string {
  const particle = koreanParticle(q, "으로/로");
  return particle === "으로(로)" ? "(으)로" : particle;
}

function quote(text: string): string {
  return `‘${text}’`;
}
