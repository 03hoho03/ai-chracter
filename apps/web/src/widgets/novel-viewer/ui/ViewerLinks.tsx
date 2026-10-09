import { Link } from "@tanstack/react-router";
import type { ComponentProps } from "react";

import type { ViewerRoute } from "../model/viewerSource";

type LinkRestProps = Omit<ComponentProps<typeof Link>, "to" | "params" | "search" | "hash">;

/** 이 소설의 작품 정보로 가는 링크 — 경로(`route`)에 따라 내 소설 또는 노벨의 작품 정보다. 받은 나머지 속성(`ref`·
 * `onClick`·`className`·자식)은 그대로 넘긴다 — `Button asChild` 의 직계 자식으로 놓여도 Radix 가 얹는 속성이 사라지지
 * 않게. */
export function NovelInfoLink({ route, novelId, ...props }: { route: ViewerRoute; novelId: string } & LinkRestProps) {
  switch (route) {
    case "owner":
      return <Link to="/novels/$novelId" params={{ novelId }} {...props} />;
    case "public":
      return <Link to="/webnovels/$novelId" params={{ novelId }} {...props} />;
  }
}

/** 이 소설의 한 화를 읽는 화면으로 가는 링크(경로 규칙은 `NovelInfoLink` 와 같다). */
export function EpisodeLink({
  route,
  novelId,
  chapterId,
  ...props
}: { route: ViewerRoute; novelId: string; chapterId: string } & LinkRestProps) {
  switch (route) {
    case "owner":
      return <Link to="/novels/$novelId/episodes/$chapterId" params={{ novelId, chapterId }} {...props} />;
    case "public":
      return <Link to="/webnovels/$novelId/episodes/$chapterId" params={{ novelId, chapterId }} {...props} />;
  }
}
