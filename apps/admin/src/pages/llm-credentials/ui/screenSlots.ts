import type { ReactNode } from "react";

import type { CredentialStateAction } from "../api/useCredentialStateMutation";
import type {
  AdminLlmCredential,
  AdminLlmCredentialCheckResponse,
  AdminLlmCredentialListResponse,
  CredentialState,
} from "../model/credential";
import type { CredentialFailure } from "../model/failure";
import type { CandidateChange, EffectiveRoute } from "../model/status";

/** 미리보기(바뀌는 첫 후보·실효 경로)가 필요한 대화상자에 넘기는 지금 화면의 목록. */
export type ScreenContext = {
  list: AdminLlmCredentialListResponse;
  route: EffectiveRoute;
};

/** 첫 후보가 바뀌는 동작(순서·켜기·끄기)을 확인받는 요청. 확정하면 대화상자 안에서 `run` 을 보낸다 — 실패하면 던진다. */
export type CandidateChangeRequest = {
  action: "reorder" | CredentialStateAction;
  credential: AdminLlmCredential;
  changes: CandidateChange[];
  run: () => Promise<void>;
};

/** `stale` 은 순서 저장이 낡은 판으로 거절돼 대화상자를 닫은 것이다 — 목록 화면이 순서 절 위에 그 문장을 안내한다. 그 밖의 실패는
 * 대화상자 안에 남고, 운영자가 닫으면 `cancelled` 다. */
export type CandidateChangeOutcome = { status: "done" } | { status: "cancelled" } | { status: "stale"; message: string };

/** 목록 화면이 직접 보낸 동작(순서·켜기·끄기·확인 호출)이 끝난 일. 알림 문구는 받는 쪽이 정한다. 순서 저장의 낡은 판 거절은 목록
 * 화면이 순서 절 위에 직접 안내하므로 여기 오지 않는다. */
export type CredentialEvent =
  | { kind: "reordered"; list: AdminLlmCredentialListResponse }
  | {
      kind: "state-changed";
      action: CredentialStateAction;
      credential: AdminLlmCredential;
      /** 누른 순간의 상태 — 소진에서 켠 것인지 알린다. */
      stateBefore: CredentialState;
    }
  | { kind: "checked"; before: AdminLlmCredentialListResponse; response: AdminLlmCredentialCheckResponse }
  | {
      kind: "failed";
      action: "reorder" | CredentialStateAction | "check";
      credential: AdminLlmCredential;
      failure: CredentialFailure;
    };

/**
 * 목록 화면이 언제 부를지만 정하고, 무엇을 보일지는 맡기는 자리 — 대화상자·알림·확인 뒤 결과 안내. 막힌 버튼(저장소 없음 등)은 목록
 * 화면이 걸러 이 함수들을 부르지 않는다.
 */
export type CredentialScreenSlots = {
  openAdd: () => void;
  openEdit: (credential: AdminLlmCredential) => void;
  openCreditBasis: (credential: AdminLlmCredential) => void;
  openReplaceSecret: (credential: AdminLlmCredential, context: ScreenContext) => void;
  openDelete: (credential: AdminLlmCredential, context: ScreenContext) => void;
  /** 목록 사용 켜기·끄기. 늘 확인을 거친다. */
  openPoolChange: (enabled: boolean, context: ScreenContext) => void;
  /** 순서·켜기·끄기가 실효 경로가 목록인 동안 첫 후보를 바꿀 때만 부른다. */
  confirmCandidateChange: (request: CandidateChangeRequest) => Promise<CandidateChangeOutcome>;
  notify: (event: CredentialEvent) => void;
  /** 확인 블록의 확인 호출 버튼 아래 자리 — 확인 뒤 결과 안내와 확인 실패 문장. */
  renderCheckNotice: (credential: AdminLlmCredential) => ReactNode;
};
