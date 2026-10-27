import { Link } from "@tanstack/react-router";
import { useId, type ReactNode } from "react";

import { useCloverPricingQuery } from "@/entities/clover";
import { useContentDetailQuery } from "@/entities/content";
import type { NovelDetailResponse } from "@/entities/novel";
import { formatDate } from "@/shared/lib/time/formatDate";

import { toNovelRightsView, type RightLine, type SourceRead } from "../model/novelRights";

const INLINE_LINK_CLASS =
  "font-medium text-foreground underline underline-offset-4 outline-none focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-ring";

/** 작품 정보의 "출처와 권리" 절 — 이 소설이 어디서 왔고(원작·원래 대화), 원작자가 지금 무엇을 허락하며, 이 소설이 이미
 * 굳혀 둔 권리(집필권·연재권)가 무엇인가. 심사 상태는 바로 아래 "노벨 공개" 절이 말하므로 여기 다시 적지 않는다.
 *
 * 원작의 지금 허락은 원작 상세 응답에서 읽는다(채팅 화면과 같은 캐시). 그 응답을 못 받아도 잠금 줄은 소설 상세만으로
 * 그린다. 카드 없이 위 경계선과 제목으로 갈리는 것은 아래 "노벨 공개" 절과 같다. */
export function NovelRightsSection({ novel }: { novel: NovelDetailResponse }) {
  const headingId = useId();
  const sourceQuery = useContentDetailQuery(novel.contentId);
  const pricing = useCloverPricingQuery().data;

  // 허락 칸은 생성 타입에서 선택 필드일 뿐 응답에는 늘 실린다 — 그래도 비어 오면 단계를 지어내지 않고 못 읽은 것으로 둔다.
  const detail = sourceQuery.data;
  let source: SourceRead = { kind: "loading" };
  if (detail?.novelPermission !== undefined)
    source = {
      kind: "loaded",
      novelPermission: detail.novelPermission,
      isOwner: detail.isOwner,
      sourceAvailable: detail.accessStatus.kind === "accessible",
    };
  else if (detail !== undefined || sourceQuery.isError) source = { kind: "unavailable" };

  const view = toNovelRightsView({ novel, source, policyV2Enabled: pricing?.novelPublicPolicyV2Enabled });

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 border-t border-border pt-6">
      <h2 id={headingId} className="text-lg font-semibold text-foreground">
        출처와 권리
      </h2>
      <dl className="flex flex-col gap-4 text-sm break-keep">
        <Row term="출처">
          {view.origin !== undefined && (
            <p className="text-foreground">
              {view.origin === "own" ? "원작자 공식 · 내 작품이 원작이에요" : "파생 · 다른 회원의 작품이 원작이에요"}
            </p>
          )}
          <p className="text-muted-foreground">
            {view.chatRoomId === null ? (
              "내 채팅으로 만들었어요. 원래 대화는 지워졌어요."
            ) : (
              <>
                내 채팅으로 만들었어요 ·{" "}
                <Link to="/chat/$roomId" params={{ roomId: view.chatRoomId }} className={INLINE_LINK_CLASS}>
                  원래 대화
                </Link>
              </>
            )}
          </p>
        </Row>

        <Row term="지금 허용 범위">
          {view.allowance.kind === "loading" && (
            <>
              <div aria-hidden className="h-5 w-32 animate-pulse rounded-md bg-muted" />
              <span className="sr-only">확인하고 있어요</span>
            </>
          )}
          {view.allowance.kind === "unavailable" && <p className="text-muted-foreground">지금은 확인할 수 없어요.</p>}
          {view.allowance.kind === "sourceDown" && (
            <>
              <p className="text-foreground">원작을 볼 수 없어요</p>
              <p className="text-muted-foreground">원작이 운영 조치로 내려가 있어요.</p>
            </>
          )}
          {view.allowance.kind === "own" && (
            <>
              <p className="text-foreground">허락이 필요 없어요</p>
              <p className="text-muted-foreground">내 작품이 원작이라 허락 단계와 상관없어요.</p>
            </>
          )}
          {view.allowance.kind === "permission" && (
            <>
              <p className="text-foreground">{view.allowance.label}</p>
              <p className="text-muted-foreground">원작자가 지금 고른 범위예요.</p>
            </>
          )}
        </Row>

        <Row term="고정된 권리">
          <div className="flex flex-col gap-3">
            <Right name="집필권" line={view.writing} />
            <Right name="연재권" line={view.serial} />
          </div>
        </Row>
      </dl>
    </section>
  );
}

/** 이름과 값 한 쌍. 좁은 화면은 이름 위·값 아래, `sm` 이상은 이름 열과 값 열로 놓는다. */
function Row({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 sm:flex-row sm:gap-4">
      <dt className="shrink-0 font-medium text-muted-foreground sm:w-28">{term}</dt>
      <dd className="flex min-w-0 flex-col gap-0.5">{children}</dd>
    </div>
  );
}

function Right({ name, line }: { name: string; line: RightLine }) {
  return (
    <div className="flex flex-col gap-0.5">
      {line.kind === "none" ? (
        <>
          <p className="text-foreground">
            <span className="font-medium">{name}</span> · 아직 없어요
          </p>
          <p className="text-muted-foreground">{line.when}</p>
        </>
      ) : (
        <>
          <p className="text-foreground tabular-nums">
            <span className="font-medium">{name}</span> · {formatDate(line.lockedAt)} 고정
          </p>
          <p className="text-muted-foreground">{line.heldPermission}</p>
          {line.effect !== undefined && <p className="text-muted-foreground">{line.effect}</p>}
        </>
      )}
    </div>
  );
}
