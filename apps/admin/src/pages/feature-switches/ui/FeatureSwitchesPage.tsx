import { useSessionQuery } from "@/entities/session";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { QueryState } from "@/shared/ui/QueryState";

import { useFeatureSwitchListQuery } from "../api/useFeatureSwitchListQuery";
import {
  ADJUSTABLE_SWITCH_COPY,
  FEATURE_SWITCH_NAMES,
  READ_ONLY_SWITCH_COPY,
  READ_ONLY_SWITCH_NAMES,
  reflectSentence,
  SWITCH_GROUPS_IN_ORDER,
  type SwitchGroup,
} from "../model/switchCopy";
import type {
  AdminAdjustableSwitch,
  AdminFeatureSwitchListResponse,
  AdminReadOnlySwitch,
  FeatureSwitchName,
} from "../model/types";
import { RollbackNotice } from "./RollbackNotice";
import { SwitchGroupSection } from "./SwitchGroupSection";
import { SwitchHistorySection } from "./SwitchHistorySection";
import { UnknownOverrideSection } from "./UnknownOverrideSection";

type FeatureSwitchesPageProps = {
  historySwitch: FeatureSwitchName | undefined;
  historyPage: number;
  onHistorySwitchChange: (switchName: FeatureSwitchName | undefined) => void;
  onHistoryPageChange: (page: number) => void;
};

/** 기능 스위치 현황판 — 지금 무엇이 켜져 있고, 바꾸면 누가 무엇을 못 하게 되는지 확인하고 바꾸는 화면. 머리·설명·「롤백
 * 전에」 상자는 쿼리 밖이라 로딩·오류에도 남는다. */
export function FeatureSwitchesPage({
  historySwitch,
  historyPage,
  onHistorySwitchChange,
  onHistoryPageChange,
}: FeatureSwitchesPageProps) {
  useDocumentTitle("기능 스위치");
  const listQuery = useFeatureSwitchListQuery();
  const meId = useSessionQuery().data?.id;

  return (
    <PageContainer>
      <PageHeader title="기능 스위치" />
      <div className="flex max-w-prose flex-col gap-2 text-sm text-muted-foreground">
        <p className="break-keep">
          어드민에서 켜고 끄는 스위치 {FEATURE_SWITCH_NAMES.length}개와 .env 로만 바꾸는 스위치 {READ_ONLY_SWITCH_NAMES.length}개의 지금
          값이에요. 덮어쓰기가 있으면 그 값으로, 없으면 .env 값으로 돌아요.
        </p>
        <ul className="flex list-disc flex-col gap-1 pl-5">
          <li className="break-keep">{reflectSentence(listQuery.data?.refreshIntervalSeconds)}</li>
          <li className="break-keep">사용자 화면은 다음에 다시 불러올 때 바뀌어요(열려 있던 웹 탭은 포커스가 돌아올 때).</li>
          <li className="break-keep">
            .env 칸은 이 서버가 기동 때 읽은 값이에요. 파일을 고쳐도 교체 전에는 바뀌지 않아요.
          </li>
        </ul>
      </div>
      <RollbackNotice />
      {/* 서버는 늘 모든 스위치를 주므로 빈 상태가 없다. */}
      <QueryState query={listQuery} errorMessage="기능 스위치 값을 불러오지 못했어요.">
        {(data) => <SwitchBoard data={data} meId={meId} />}
      </QueryState>
      <SwitchHistorySection
        switchName={historySwitch}
        page={historyPage}
        meId={meId}
        onSwitchChange={onHistorySwitchChange}
        onPageChange={onHistoryPageChange}
      />
    </PageContainer>
  );
}

function SwitchBoard({ data, meId }: { data: AdminFeatureSwitchListResponse; meId: string | undefined }) {
  const grouped = groupSwitches(data);

  return (
    <>
      {data.unknownOverrides.length > 0 && (
        <UnknownOverrideSection
          overrides={data.unknownOverrides}
          refreshSeconds={data.refreshIntervalSeconds}
          meId={meId}
        />
      )}
      {SWITCH_GROUPS_IN_ORDER.map((group) => (
        <SwitchGroupSection
          key={group}
          group={group}
          adjustable={grouped.adjustable.get(group) ?? []}
          readOnly={grouped.readOnly.get(group) ?? []}
          list={data}
          meId={meId}
        />
      ))}
    </>
  );
}

/** 서버 응답을 이 화면의 묶음·순서로 다시 배치한다. 행 순서는 사람이 읽는 이름 사전에 적은 순서다. 사전을 기준으로 돌아서,
 * 사전에 없는 이름(이 화면보다 새 서버가 더한 스위치)은 그릴 이름·설명이 없어 건너뛴다 — 서버가 먼저 배포되고 이 화면이 아직
 * 옛 판인 동안에만 생긴다. */
function groupSwitches(data: AdminFeatureSwitchListResponse) {
  const adjustable = new Map<SwitchGroup, AdminAdjustableSwitch[]>();
  const readOnly = new Map<SwitchGroup, AdminReadOnlySwitch[]>();
  const adjustableByName = new Map(data.adjustable.map((item) => [item.name, item]));
  for (const name of FEATURE_SWITCH_NAMES) {
    const item = adjustableByName.get(name);
    if (item === undefined) continue;
    const group = ADJUSTABLE_SWITCH_COPY[name].group;
    adjustable.set(group, [...(adjustable.get(group) ?? []), item]);
  }
  const readOnlyByName = new Map(data.readOnly.map((item) => [item.name, item]));
  for (const name of READ_ONLY_SWITCH_NAMES) {
    const item = readOnlyByName.get(name);
    if (item === undefined) continue;
    const group = READ_ONLY_SWITCH_COPY[name].group;
    readOnly.set(group, [...(readOnly.get(group) ?? []), item]);
  }
  return { adjustable, readOnly };
}
