import { cn } from "@ai-character-chat/ui/lib/utils";
import type { MouseEvent } from "react";

import { useFeatureSwitchListQuery } from "../api/useFeatureSwitchListQuery";
import { onOffText, switchLabelOf } from "../model/switchCopy";
import type { AdminFeatureSwitchListResponse } from "../model/types";
import { switchHeadingId, UNKNOWN_OVERRIDES_HEADING_ID } from "./elementIds";
import { SECTION_CARD_CLASS, TEXT_LINK_CLASS } from "./styles";

/**
 * 「롤백 전에」 상자. 덮어쓰기는 DB 표에 남아 옛 이미지로 롤백해도 지워지지 않고, 새 이미지를 다시 올리는 순간 되살아난다 —
 * 그래서 덮어쓰기가 없어도 상자와 절차 문단은 늘 있다. 목록 줄만 쿼리를 따른다(머리·문단은 로딩·오류에도 남는다).
 */
export function RollbackNotice() {
  const listQuery = useFeatureSwitchListQuery();
  const data = listQuery.data;
  const hasOverrides = data !== undefined && overrideCount(data) > 0;

  return (
    <section aria-labelledby="feature-switch-rollback-heading" className={SECTION_CARD_CLASS}>
      <h2 id="feature-switch-rollback-heading" className="text-lg font-semibold text-foreground">
        롤백 전에
      </h2>
      <OverrideSummary data={data} isPending={listQuery.isPending} />
      <p className={cn("max-w-prose text-sm break-keep", hasOverrides ? "text-foreground" : "text-muted-foreground")}>
        옛 이미지로 롤백하기 전에 이 목록을 보고, 남길 값은 .env 에 옮겨 적고 태그 없는 교체로 반영한 뒤 덮어쓰기를 지우세요 —
        .env 는 교체 때만 읽혀서, 반영 전에 지우면 롤백이 끝날 때까지 서버가 옛 .env 값으로 돌아요. 덮어쓰기를 모르는 옛 이미지는
        .env 값으로 돌고, 지우지 않은 덮어쓰기는 새 이미지를 다시 올리는 순간(롤백 중 다른 PR 병합의 자동 배포 포함) 되살아나
        .env 값을 이겨요.
      </p>
    </section>
  );
}

function overrideCount(data: AdminFeatureSwitchListResponse) {
  return data.adjustable.filter((item) => item.override !== null).length + data.unknownOverrides.length;
}

function OverrideSummary({ data, isPending }: { data: AdminFeatureSwitchListResponse | undefined; isPending: boolean }) {
  // 진행 표시라 `motion-safe:` 로 가드하지 않는다 — 멈추면 "멈춘 화면"으로 읽힌다.
  if (isPending) return <div aria-busy className="h-5 w-64 max-w-full animate-pulse rounded bg-secondary" />;
  if (data === undefined) return <p className="text-sm text-destructive-text">덮어쓰기 목록을 불러오지 못했어요.</p>;

  const count = overrideCount(data);
  if (count === 0) {
    return <p className="text-sm text-muted-foreground">지금 덮어쓰기는 없어요 — 모든 스위치가 .env 값으로 돌아요.</p>;
  }

  const unknownCount = data.unknownOverrides.length;
  return (
    <div className="flex flex-col gap-1.5 text-sm text-foreground">
      <p>지금 덮어쓰기 {count}개:</p>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
        {data.adjustable.map((item) =>
          item.override === null ? null : (
            <li key={item.name} className="min-w-0 wrap-anywhere">
              <a
                href={`#${switchHeadingId(item.name)}`}
                className={TEXT_LINK_CLASS}
                onClick={(event) => focusById(event, switchHeadingId(item.name))}
              >
                {/* 이 화면보다 새 서버가 더한 스위치면 사람 이름이 없어 코드 이름으로 보인다. */}
                {switchLabelOf(item.name) ?? item.name}
                <span aria-hidden> → </span>
                {/* 화살표는 읽히지 않아 이름과 값이 붙어 들리지 않게 숨김 구분을 둔다. */}
                <span className="sr-only">: </span>
                {onOffText(item.override.value)}
              </a>
            </li>
          ),
        )}
        {unknownCount > 0 && (
          <li>
            <a
              href={`#${UNKNOWN_OVERRIDES_HEADING_ID}`}
              className={TEXT_LINK_CLASS}
              onClick={(event) => focusById(event, UNKNOWN_OVERRIDES_HEADING_ID)}
            >
              이 이미지가 모르는 덮어쓰기 {unknownCount}개 포함
            </a>
          </li>
        )}
      </ul>
    </div>
  );
}

/** 주소의 해시를 바꾸지 않고(라우터 기록이 쌓이지 않게) 그 제목으로 포커스를 옮긴다 — 포커스가 그 자리로 스크롤한다. */
function focusById(event: MouseEvent<HTMLAnchorElement>, id: string) {
  const target = document.getElementById(id);
  if (target === null) return;
  event.preventDefault();
  target.focus();
}
