import { Link } from "@tanstack/react-router";

import { PREMIUM_OFF_UNREAD_COPY, useRoutingQuery, type RoutingLane } from "@/entities/prompt-routing";

import { chainReaders, describeReader } from "../model/chainReads";
import type { PromptModel } from "../model/model";

type ChainReadByProps = {
  lane: RoutingLane;
  model: PromptModel;
};

/** 이 체인을 운영에서 어느 칸이 읽는지. 원천은 모델 배정 표 조회 하나다(배정 표를 저장·되돌리면 그 쿼리가 무효화되어 다음
 * 조회 때 바뀐다). 상위 모델 스위치가 꺼져 실행되지 않는 Opus 방 칸은 읽는 칸과 따로 보인다. 로딩·실패를 "읽는 칸 없음"과
 * 섞지 않는다 — 조회가 실패한 순간에도 실제로는 읽는 칸이 있을 수 있다. */
export function ChainReadBy({ lane, model }: ChainReadByProps) {
  const routingQuery = useRoutingQuery();

  if (routingQuery.isPending) {
    return <p className="text-xs text-muted-foreground">운영 읽힘 확인 중...</p>;
  }

  if (routingQuery.isError) {
    return <p className="text-xs text-destructive-text">운영 읽힘을 확인하지 못했어요.</p>;
  }

  const { live, switchedOff } = chainReaders(routingQuery.data, lane, model);
  const switchedOffLine = switchedOff.length > 0 && (
    <p className="max-w-prose break-keep text-xs text-muted-foreground">
      <span className="font-medium text-foreground">{PREMIUM_OFF_UNREAD_COPY}</span>{" "}
      {switchedOff.map(describeReader).join(" · ")}
    </p>
  );

  if (live.length === 0) {
    return (
      <div className="flex flex-col gap-1">
        <p className="max-w-prose break-keep text-xs text-foreground">
          지금 운영에서 이 체인을 읽는 칸이 없어요.{" "}
          {switchedOff.length > 0
            ? "게시해도 상위 모델을 켜기 전까지 쓰이지 않아요."
            : "게시해도 모델 배정 표가 이 체인을 고르기 전까지 쓰이지 않아요."}{" "}
          <Link
            to="/prompt-routing"
            className="admin-hit-area font-medium text-primary hover:underline focus-visible:underline"
          >
            모델 배정 열기
          </Link>
        </p>
        {switchedOffLine}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <p className="max-w-prose break-keep text-xs text-muted-foreground">
        <span className="font-medium text-foreground">운영에서 읽는 칸</span> {live.map(describeReader).join(" · ")}
      </p>
      {switchedOffLine}
    </div>
  );
}
