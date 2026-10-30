import { useEffect, useState } from "react";

/**
 * 일이 도는 동안 지난 초. 오래 걸리는 요청(런 루트 훑기)은 움직이는 막대 대신 이 숫자로 진행을 보인다 — 동작 줄이기 설정에서도
 * 그대로 읽히고, 멈춘 화면과 기다리는 화면이 갈린다.
 */
export function useElapsedSeconds(isRunning: boolean): number {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    if (!isRunning) return;
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => {
      window.clearInterval(timer);
      setSeconds(0);
    };
  }, [isRunning]);

  return seconds;
}
