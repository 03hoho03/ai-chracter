import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { QueryState } from "@/shared/ui/QueryState";

import { useLlmCredentialsQuery } from "../api/useLlmCredentialsQuery";
import { useRuntimeSwitchQuery } from "../api/useRuntimeSwitchQuery";
import type { AdminLlmCredentialListResponse } from "../model/credential";
import {
  LIST_LOAD_ERROR_TEXT,
  NOTIFICATIONS_MISSING_TEXT,
  PAGE_INTRO_TEXT,
  SPEND_CAUTION_TEXT,
  UNREADABLE_SECRET_SCOPE_TEXT,
} from "../model/labels";
import { effectiveRoute, firstCandidates } from "../model/status";
import { AddCredentialButton } from "./AddCredentialButton";
import { CredentialList } from "./CredentialList";
import { PoolSection, type RuntimeSwitchState } from "./PoolSection";
import type { CredentialScreenSlots } from "./screenSlots";
import { StoreNotice } from "./StoreNotice";

/**
 * 대화상자·알림을 붙이기 전의 자리. 할 일: 추가·이름 수정·충전액·키 교체·삭제·목록 사용 대화상자와 범용 확인 대화상자를 만들어 이
 * 함수들에서 열고, 알림과 확인 뒤 결과 안내를 채운다. 그때까지 그 버튼들은 눌러도 아무 일도 하지 않고, 첫 후보가 바뀌는 동작은 확인 없이
 * 보내지 않도록 취소로 끝낸다.
 */
const UNATTACHED_SLOTS: CredentialScreenSlots = {
  openAdd: () => undefined,
  openEdit: () => undefined,
  openCreditBasis: () => undefined,
  openReplaceSecret: () => undefined,
  openDelete: () => undefined,
  openPoolChange: () => undefined,
  confirmCandidateChange: () => Promise.resolve({ status: "cancelled" }),
  notify: () => undefined,
  renderCheckNotice: () => null,
};

export function LlmCredentialsPage() {
  useDocumentTitle("Claude 자격");
  const listQuery = useLlmCredentialsQuery();
  const switchQuery = useRuntimeSwitchQuery();
  const slots = UNATTACHED_SLOTS;
  // 목록을 읽기 전에는 저장소 설정을 모른다 — 막지 않고, 서버가 503 으로 답하면 그때 띠가 나타난다.
  const isStoreMissing = listQuery.data?.storeConfigured === false;

  const runtimeSwitch = toRuntimeSwitchState(switchQuery);

  return (
    <PageContainer>
      <PageHeader
        title="Claude 자격"
        actions={<AddCredentialButton variant="default" isBlocked={isStoreMissing} onAdd={slots.openAdd} />}
      />
      <p className="max-w-prose break-keep text-sm text-muted-foreground">{PAGE_INTRO_TEXT}</p>
      {/* 화면을 막는 것은 자격 목록 하나다. 서버 스위치 조회는 따로 살려, 실패해도 실효 경로가 "알 수 없음"이 될 뿐이다. */}
      <QueryState query={listQuery} errorMessage={LIST_LOAD_ERROR_TEXT}>
        {(list) => (
          <CredentialsScreen
            list={list}
            isListFetching={listQuery.isFetching}
            runtimeSwitch={runtimeSwitch}
            slots={slots}
          />
        )}
      </QueryState>
    </PageContainer>
  );
}

type CredentialsScreenProps = {
  list: AdminLlmCredentialListResponse;
  isListFetching: boolean;
  runtimeSwitch: RuntimeSwitchState;
  slots: CredentialScreenSlots;
};

function CredentialsScreen({ list, isListFetching, runtimeSwitch, slots }: CredentialsScreenProps) {
  const route = effectiveRoute(list, runtimeSwitch.status === "ready" ? runtimeSwitch.value : undefined);
  const firsts = firstCandidates(list.credentials);
  const hasCredit = list.credentials.some((credential) => credential.creditUsd !== null);

  return (
    <>
      {!list.storeConfigured && <StoreNotice />}
      {!list.notificationsConfigured && <p className="break-keep text-xs text-muted-foreground">{NOTIFICATIONS_MISSING_TEXT}</p>}
      <PoolSection
        list={list}
        route={route}
        firsts={firsts}
        runtimeSwitch={runtimeSwitch}
        onPoolChange={(enabled) => slots.openPoolChange(enabled, { list, route })}
      />
      <CredentialList list={list} route={route} firsts={firsts} isListFetching={isListFetching} slots={slots} />
      {list.credentials.length > 0 && (
        <div className="flex max-w-prose flex-col gap-2">
          {hasCredit && <p className="break-keep text-sm text-muted-foreground">{SPEND_CAUTION_TEXT}</p>}
          <p className="break-keep text-xs text-muted-foreground">{UNREADABLE_SECRET_SCOPE_TEXT}</p>
        </div>
      )}
    </>
  );
}

type RuntimeSwitchQueryLike = {
  data: boolean | undefined;
  isPending: boolean;
  isFetching: boolean;
  failureCount: number;
  refetch: () => Promise<unknown>;
};

/** 서버 스위치 조회를 경로 줄이 쓰는 상태로. 첫 시도 중만 "읽는 중"이고, 재시도 중·실패·그 칸이 없는 옛 서버는 모두 "읽지 못함"이다 —
 * 재시도 중에도 대기로 두면 실패한 조회가 기본 재시도 동안 "읽는 중"에 머문다. */
function toRuntimeSwitchState(query: RuntimeSwitchQueryLike): RuntimeSwitchState {
  if (query.data !== undefined) return { status: "ready", value: query.data };
  if (query.isPending && query.failureCount === 0) return { status: "pending" };
  return { status: "failed", isRetrying: query.isFetching, retry: () => void query.refetch() };
}
