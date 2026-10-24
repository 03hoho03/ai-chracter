/** 방 기억(노트·요약). `summary`는 첫 접기 전이면 없다. `rolledBackAt`은 지난 메시지를 고치거나 지워 요약이
 * 이전 판으로 돌아간 마지막 시각이고, 그런 적이 없거나 초기화했으면 없다. `features`는 서버 스위치다 —
 * `itemsVisible`이 거짓이면 장면·사실 목록과 잊게 하기·요약 다시 만들기 라우트가 닫혀 있어 패널이 그것들을 그리지도
 * 부르지도 않는다. `summaryFolding`은 긴 대화를 요약으로 접는 일이 켜져 있는가다. */
export type ChatRoomMemory = {
  note: string;
  summary?: ChatRoomMemorySummary;
  version: number;
  rolledBackAt?: string;
  limits: { noteMaxLength: number; summaryMaxLength: number };
  features: { itemsVisible: boolean; summaryFolding: boolean };
};

/** 방의 현재 요약. `canRevert`는 사용자가 이 요약을 고친 적이 있어 고치기 직전 본문으로 한 번 되돌릴 수
 * 있는가다 — AI가 새로 접은 요약은 되돌릴 대상이 없다. */
export type ChatRoomMemorySummary = {
  text: string;
  source: "auto" | "user";
  canRevert: boolean;
  updatedAt: string;
};
