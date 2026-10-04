import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CURATION_WAIT_LIMIT_MS, createCurationWaitCap } from "./curationWaitCap";

function setup() {
  const onGiveUp = vi.fn<() => void>();
  const cap = createCurationWaitCap(onGiveUp);
  return { onGiveUp, cap };
}

describe("createCurationWaitCap", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("그리드를 상한만큼 붙잡으면 정확히 그 순간 한 번 포기한다", () => {
    const { onGiveUp, cap } = setup();
    cap.update(true);

    vi.advanceTimersByTime(CURATION_WAIT_LIMIT_MS - 1);
    expect(onGiveUp).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onGiveUp).toHaveBeenCalledTimes(1);
  });

  it("렌더마다 같은 값을 다시 넘겨도 시계를 새로 시작하지 않는다", () => {
    const { onGiveUp, cap } = setup();
    cap.update(true);
    vi.advanceTimersByTime(CURATION_WAIT_LIMIT_MS - 1);
    cap.update(true);
    vi.advanceTimersByTime(1);
    expect(onGiveUp).toHaveBeenCalledTimes(1);

    // 두 번째 예약이 숨어 있었다면 여기서 한 번 더 알린다.
    vi.advanceTimersByTime(CURATION_WAIT_LIMIT_MS);
    expect(onGiveUp).toHaveBeenCalledTimes(1);
  });

  it("상한 전에 응답이 오면(붙잡기가 풀리면) 포기하지 않는다", () => {
    const { onGiveUp, cap } = setup();
    cap.update(true);
    vi.advanceTimersByTime(CURATION_WAIT_LIMIT_MS - 1);
    cap.update(false);
    vi.advanceTimersByTime(CURATION_WAIT_LIMIT_MS * 2);

    expect(onGiveUp).not.toHaveBeenCalled();
  });

  it("다시 붙잡으면 처음부터 잰다", () => {
    const { onGiveUp, cap } = setup();
    cap.update(true);
    vi.advanceTimersByTime(CURATION_WAIT_LIMIT_MS - 1);
    cap.update(false);
    cap.update(true);

    vi.advanceTimersByTime(CURATION_WAIT_LIMIT_MS - 1);
    expect(onGiveUp).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onGiveUp).toHaveBeenCalledTimes(1);
  });

  it("한 번 포기하면 다시 붙잡아도 또 알리지 않는다", () => {
    const { onGiveUp, cap } = setup();
    cap.update(true);
    vi.advanceTimersByTime(CURATION_WAIT_LIMIT_MS);
    cap.update(false);
    cap.update(true);
    vi.advanceTimersByTime(CURATION_WAIT_LIMIT_MS * 2);

    expect(onGiveUp).toHaveBeenCalledTimes(1);
  });

  it("화면이 내려가면(dispose) 예약을 지운다", () => {
    const { onGiveUp, cap } = setup();
    cap.update(true);
    cap.dispose();
    vi.advanceTimersByTime(CURATION_WAIT_LIMIT_MS * 2);

    expect(onGiveUp).not.toHaveBeenCalled();
  });

  it("상한은 1초 이상 2초 이하다 — 목록이 다 온 뒤 큐레이션 하나로 그리드를 그 이상 붙잡지 않는다", () => {
    expect(CURATION_WAIT_LIMIT_MS).toBeGreaterThanOrEqual(1_000);
    expect(CURATION_WAIT_LIMIT_MS).toBeLessThanOrEqual(2_000);
  });
});
