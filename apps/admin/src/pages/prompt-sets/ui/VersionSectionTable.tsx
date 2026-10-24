import { Button } from "@ai-character-chat/ui/components/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";

import { DenseTable } from "@/shared/ui/DenseTable";

import type { AdminPromptSetDetailResponse } from "../api/usePublishMutation";
import {
  isChannelEditableInLane,
  isPromptChannel,
  promptSectionLabel,
  SPEAKER_LABELS_SECTION,
} from "../model/channels";
import { semverText, type AdminPromptSectionSemver } from "../model/semver";
import { RestoreSectionDialog } from "./RestoreSectionDialog";

type VersionSectionTableProps = {
  detail: AdminPromptSetDetailResponse;
  /** 이 체인 폼에 저장 안 한 편집이 있어 복원을 막는다. 그 사유를 보이는 요소의 id 를 함께 받아 버튼 설명으로 잇는다. */
  restoreBlockedBy: string | null;
};

/** 게시본의 체인 판과 섹션마다의 판, 그리고 섹션 하나만 초안으로 가져오는 버튼. 판을 매기기 전에 게시된 옛 버전은 판 대신 그
 * 사실을 알리고, 섹션 목록만 세트의 채널에서 뽑아 보인다(화자 라벨 넷은 한 섹션으로 묶는다). */
export function VersionSectionTable({ detail, restoreBlockedBy }: VersionSectionTableProps) {
  const hasSemver = detail.semver != null;
  const rows = sectionRows(detail);
  const isBlocked = restoreBlockedBy !== null;

  return (
    <div className="flex flex-col gap-2">
      <p className="break-keep text-sm text-foreground">
        {hasSemver ? (
          <>
            판 <span className="font-medium tabular-nums">{detail.semver}</span> · 섹션 {rows.length}개
          </>
        ) : (
          `판을 매기기 전에 게시된 버전이에요(${semverText(detail.semver, detail.version)}). 섹션 ${rows.length}개`
        )}
      </p>
      <div className="overflow-hidden rounded-lg border border-border">
        <DenseTable surface="card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">섹션</TableHead>
                {hasSemver && <TableHead scope="col">판</TableHead>}
                {hasSemver && <TableHead scope="col">이번 게시에서</TableHead>}
                <TableHead scope="col">
                  <span className="sr-only">섹션 복원</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => {
                const label = promptSectionLabel(row.channel);
                return (
                  <TableRow key={row.channel}>
                    <TableHead scope="row" className="font-medium">
                      {label}
                    </TableHead>
                    {hasSemver && <TableCell className="tabular-nums">{row.semver ?? "-"}</TableCell>}
                    {hasSemver && (
                      <TableCell>{row.level == null ? "그대로" : `${row.level} 로 올림`}</TableCell>
                    )}
                    <TableCell className="text-right">
                      {isRestorableSection(detail, row.channel) && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          aria-disabled={isBlocked}
                          aria-describedby={restoreBlockedBy ?? undefined}
                          className="admin-hit-area aria-disabled:opacity-65"
                          onClick={() => {
                            if (isBlocked) return;
                            void RestoreSectionDialog.call({
                              id: detail.id,
                              version: detail.version,
                              section: row.channel,
                              lane: detail.lane,
                              model: detail.model,
                            });
                          }}
                        >
                          이 섹션만 초안으로
                          {/* 보이는 글자를 이름 앞에 그대로 두고(음성 명령이 그 글자로 찾는다) 어느 섹션·버전인지만 덧붙인다. */}
                          <span className="sr-only">
                            {" "}
                            복원: {label}, v{detail.version ?? "?"}
                          </span>
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </DenseTable>
      </div>
      {hasSemver && detail.removedSections && detail.removedSections.length > 0 && (
        <p className="break-keep text-xs text-muted-foreground">
          이번 게시에서 빠진 섹션: {detail.removedSections.map(promptSectionLabel).join(", ")}
        </p>
      )}
    </div>
  );
}

type SectionRow = Pick<AdminPromptSectionSemver, "channel"> & Partial<Omit<AdminPromptSectionSemver, "channel">>;

/** 판이 있으면 서버의 섹션 판 목록이 원천이다. 옛 게시본은 판 행이 없어 세트의 채널(중복 제거) + 화자 라벨로 섹션을 만든다. */
function sectionRows(detail: AdminPromptSetDetailResponse): SectionRow[] {
  if (detail.sectionSemvers && detail.sectionSemvers.length > 0) return detail.sectionSemvers;
  const channels = [...new Set(detail.sections.map((section) => section.channel))];
  return [...channels, SPEAKER_LABELS_SECTION].map((channel) => ({ channel }));
}

/** 채팅 레인의 소설 섹션은 게시 때 직전 게시본 값으로 고정돼 편집기에도 보이지 않는다 — 복원해도 서버가 거부하므로 버튼을 두지
 * 않는다. 지금 코드가 모르는 채널도 이 체인에 없는 섹션이라 두지 않는다. */
function isRestorableSection(detail: AdminPromptSetDetailResponse, section: string): boolean {
  if (section === SPEAKER_LABELS_SECTION) return true;
  return isPromptChannel(section) && isChannelEditableInLane(detail.lane, section);
}
