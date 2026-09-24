import { Button } from "@ai-character-chat/ui/components/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Check } from "lucide-react";
import { useState } from "react";

import { formatDateTime } from "@/shared/lib/format/formatDateTime";

import { useVersionDetailQuery } from "../api/useVersionDetailQuery";
import { useVersionListQuery } from "../api/useVersionListQuery";
import { PROMPT_LANE_LABELS } from "../model/lane";
import { RestorePromptSetDialog } from "./RestorePromptSetDialog";

/** 제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 `VersionTable`로 갈라낸다
 * (`pages/appeals`의 `AppealsTable`과 같은 결). */
export function VersionHistorySection() {
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <h2 className="text-lg font-semibold text-foreground">게시 이력</h2>
      <VersionTable />
    </section>
  );
}

/** `GET /admin/prompt-sets`는 게시된 버전뿐 아니라 현재 초안 행(`status: "draft"`, `version:
 * null`)도 함께 내려온다(D-16이 말하는 "이력"이 아니다) — 그래서 여기서 `published`만 걸러
 * 보여준다. 선택한 행의 라벨·섹션 개수는 목록에 없어(메타만, D-16) `GET /{id}`로 따로 받는다
 * (appeals의 "목록에서 find" 패턴을 못 쓰는 이유이기도 하다). */
function VersionTable() {
  const versionListQuery = useVersionListQuery();
  const [selectedId, setSelectedId] = useState<string>();

  if (versionListQuery.isPending) {
    return <div className="h-32 animate-pulse rounded-lg bg-secondary" />;
  }

  if (versionListQuery.isError) {
    return <p className="text-sm text-destructive-text">게시 이력을 불러오지 못했어요.</p>;
  }

  const publishedVersions = versionListQuery.data.items.filter((item) => item.status === "published");

  if (publishedVersions.length === 0) {
    return (
      <p className="break-keep text-sm text-muted-foreground">
        아직 게시된 버전이 없어요. 초안을 저장하고 처음 게시하면 여기 버전이 쌓여요.
      </p>
    );
  }

  return (
    <>
      <div className="overflow-hidden rounded-lg border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>
                {/* 값 칸의 체크 글리프 슬롯(size-4 + gap-1.5)만큼 비워 `버전`과 `vN`의 왼쪽 끝을 맞춘다. */}
                <span className="inline-flex items-center gap-1.5">
                  <span aria-hidden className="size-4" />
                  버전
                </span>
              </TableHead>
              <TableHead>레인</TableHead>
              <TableHead>게시일</TableHead>
              <TableHead>메모</TableHead>
              <TableHead>상태</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {publishedVersions.map((item) => {
              const isSelected = item.id === selectedId;
              return (
                // 선택 채움은 `secondary`다 — 공용 `TableRow`의 `bg-muted`는 이 표가 앉은 `bg-card`와
                // 같은 값이라 선택이 1.0000:1로 사라지고, 공용 hover `muted/50`도 같은 이유로 안 보여
                // 호출부에서 둘 다 덮는다(Q-9: 공용 기본값은 두고 호출부만 덮는다). 채움은 card 대비
                // 1.12:1뿐이라 선택을 전달하는 3:1 단서로 체크 글리프를 함께 둔다(`foreground` on
                // `secondary` 14.06:1, BS-22). 자리를 늘 비워 두어 선택이 바뀌어도 열 폭이 흔들리지 않는다.
                // 행 전체 클릭은 두되 키보드·보조기술 진입점은 첫 셀의 네이티브 버튼이다 — `<tr
                // role="button">`은 표의 행·열 의미를 지우고 `aria-selected`도 무효가 된다. 버튼엔
                // onClick이 없다: Enter/Space가 만든 네이티브 click이 `tr`의 onClick으로 한 번만
                // 버블된다(backlog-l-goal-prompt.md BL-8).
                <TableRow
                  key={item.id}
                  className={cn(
                    "cursor-pointer hover:bg-secondary/50",
                    isSelected && "bg-secondary hover:bg-secondary",
                  )}
                  onClick={() => setSelectedId(item.id)}
                >
                  <TableCell>
                    <button
                      type="button"
                      aria-current={isSelected || undefined}
                      className="flex w-full items-center gap-1.5 rounded-sm text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                    >
                      <Check aria-hidden className={cn("size-4 text-foreground", !isSelected && "invisible")} />
                      v{item.version}
                      <span className="sr-only">, {PROMPT_LANE_LABELS[item.lane]}</span>
                    </button>
                  </TableCell>
                  <TableCell>{PROMPT_LANE_LABELS[item.lane]}</TableCell>
                  <TableCell>{formatDateTime(item.publishedAt)}</TableCell>
                  <TableCell className="max-w-64 truncate">{item.note || "-"}</TableCell>
                  <TableCell>{item.isActive ? "활성" : "-"}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {selectedId !== undefined && <VersionDetailPanel id={selectedId} />}
    </>
  );
}

type VersionDetailPanelProps = {
  id: string;
};

function VersionDetailPanel({ id }: VersionDetailPanelProps) {
  const versionDetailQuery = useVersionDetailQuery(id);

  if (versionDetailQuery.isPending) {
    return <div className="h-24 animate-pulse rounded-lg bg-secondary" />;
  }

  if (versionDetailQuery.isError) {
    return <p className="text-sm text-destructive-text">버전 상세를 불러오지 못했어요.</p>;
  }

  const detail = versionDetailQuery.data;

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border p-4">
      <dl className="grid grid-cols-1 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-2">
        <div className="flex flex-col">
          <dt className="text-xs text-muted-foreground">사용자 라벨</dt>
          <dd className="text-foreground">{detail.labels.userLabel}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-xs text-muted-foreground">스토리 진행자 라벨</dt>
          <dd className="text-foreground">{detail.labels.storyAssistantLabel}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-xs text-muted-foreground">스토리 전개 예시 라벨</dt>
          <dd className="text-foreground">{detail.labels.storyExampleLabel}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-xs text-muted-foreground">캐릭터 라벨</dt>
          <dd className="text-foreground">{detail.labels.characterAssistantLabel}</dd>
        </div>
      </dl>
      <p className="text-xs text-muted-foreground">섹션 {detail.sections.length}개</p>
      <div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            void RestorePromptSetDialog.call({
              id: detail.id,
              version: detail.version,
              publishedAt: detail.publishedAt,
              lane: detail.lane,
            })
          }
        >
          이 버전으로 복원
        </Button>
      </div>
    </div>
  );
}
