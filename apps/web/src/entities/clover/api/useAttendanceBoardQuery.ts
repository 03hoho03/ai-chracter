import { useQuery } from "@tanstack/react-query";

import { attendanceBoardQueryOptions } from "./attendanceBoardQueryOptions";

/** `enabled` 는 비로그인(물으면 401)과 출석 스위치가 꺼진 동안(물으면 404)에 판을 묻지 않게 끄는 자리다. */
export function useAttendanceBoardQuery({ enabled }: { enabled: boolean }) {
  return useQuery({ ...attendanceBoardQueryOptions(), enabled });
}
