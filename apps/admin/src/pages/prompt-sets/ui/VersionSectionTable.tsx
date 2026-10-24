import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";

import { DenseTable } from "@/shared/ui/DenseTable";

import type { AdminPromptSetDetailResponse } from "../api/usePublishMutation";
import { promptSectionLabel, SPEAKER_LABELS_SECTION } from "../model/channels";
import { semverText, type AdminPromptSectionSemver } from "../model/semver";

type VersionSectionTableProps = {
  detail: AdminPromptSetDetailResponse;
};

/** 게시본의 체인 판과 섹션마다의 판. 판을 매기기 전에 게시된 옛 버전은 판 대신 그 사실을 알리고, 섹션 목록만 세트의 채널에서
 * 뽑아 보인다(화자 라벨 넷은 한 섹션으로 묶는다). */
export function VersionSectionTable({ detail }: VersionSectionTableProps) {
  const hasSemver = detail.semver != null;
  const rows = sectionRows(detail);

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
      {hasSemver && (
        <div className="overflow-hidden rounded-lg border border-border">
          <DenseTable surface="card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">섹션</TableHead>
                  <TableHead scope="col">판</TableHead>
                  <TableHead scope="col">이번 게시에서</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.channel}>
                    <TableHead scope="row" className="font-medium">
                      {promptSectionLabel(row.channel)}
                    </TableHead>
                    <TableCell className="tabular-nums">{row.semver}</TableCell>
                    <TableCell>{row.level === null ? "그대로" : `${row.level} 로 올림`}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </DenseTable>
        </div>
      )}
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
