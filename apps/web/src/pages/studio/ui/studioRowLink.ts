import type { LinkProps } from "@tanstack/react-router";

import type { StudioActionTarget } from "../model/studioWorkRow";

/** 다음 행동의 목적지를 `<Link>` 에 넘길 꼴로. 행과 이어 만들기 카드가 함께 쓴다. */
export function toStudioLinkProps(target: StudioActionTarget): LinkProps {
  return target.kind === "novel"
    ? { to: "/novels/$novelId", params: { novelId: target.id } }
    : { to: "/builder/$type/$draftId", params: { type: target.type, draftId: target.id } };
}
