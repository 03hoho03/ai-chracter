import { Button } from "@ai-character-chat/ui/components/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { useState } from "react";

import { formatDateTime } from "@/shared/lib/format/formatDateTime";

import { useVersionDetailQuery } from "../api/useVersionDetailQuery";
import { useVersionListQuery } from "../api/useVersionListQuery";
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
    return <div className="h-32 animate-pulse rounded-lg bg-muted" />;
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
              <TableHead>버전</TableHead>
              <TableHead>게시일</TableHead>
              <TableHead>메모</TableHead>
              <TableHead>상태</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {publishedVersions.map((item) => (
              <TableRow
                key={item.id}
                tabIndex={0}
                role="button"
                aria-selected={item.id === selectedId}
                className="cursor-pointer aria-selected:bg-muted"
                onClick={() => setSelectedId(item.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelectedId(item.id);
                  }
                }}
              >
                <TableCell>v{item.version}</TableCell>
                <TableCell>{formatDateTime(item.publishedAt)}</TableCell>
                <TableCell className="max-w-64 truncate">{item.note || "-"}</TableCell>
                <TableCell>{item.isActive ? "활성" : "-"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {selectedId && <VersionDetailPanel id={selectedId} />}
    </>
  );
}

type VersionDetailPanelProps = {
  id: string;
};

function VersionDetailPanel({ id }: VersionDetailPanelProps) {
  const versionDetailQuery = useVersionDetailQuery(id);

  if (versionDetailQuery.isPending) {
    return <div className="h-24 animate-pulse rounded-lg bg-muted" />;
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
            })
          }
        >
          이 버전으로 복원
        </Button>
      </div>
    </div>
  );
}
