import type { HostedVersion } from "@/shared/api/service/serviceClient";
import { formatCount } from "@/shared/lib/formatNumber";

const KIB = 1024;
const MIB = 1024 * KIB;

/** 판 칸에 적는 커밋 약칭 길이. 온 커밋은 `title` 로 단다. */
const SHORT_COMMIT_LENGTH = 7;

/** 판 칸 — 최신 판 번호와 살아 있는 판 수. 서비스는 지운 판까지 세어 번호를 매겨, 번호만 보면 판이 몇 개 살아 있는지 모른다. */
export function versionNumberText(version: HostedVersion, versionCount: number): string {
  return `${version.versionNumber} · 살아 있는 판 ${formatCount(versionCount)}개`;
}

/** 크기 칸 — 압축(올린 크기)과 푼 크기. */
export function versionSizeText(version: HostedVersion): string {
  return `압축 ${formatBytes(version.compressedSize)} · 푼 ${formatBytes(version.uncompressedSize)}`;
}

/** 올린 때 — 서비스가 UTC 로 적은 시각을 보는 사람의 시간대로(`11-05 14:02`). 읽지 못하면 받은 글 그대로. */
export function uploadedAtText(version: HostedVersion): string {
  const date = new Date(version.uploadedAt);
  if (Number.isNaN(date.getTime())) return version.uploadedAt;
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 묶음을 만든 측정 서버 checkout 의 커밋 약칭. */
export function shortCommit(version: HostedVersion): string {
  return version.sourceCommit.commit.slice(0, SHORT_COMMIT_LENGTH);
}

/**
 * 바이트 수. MiB 아래는 KiB 로 적는다 — 작은 묶음이 `0.0MiB` 로 적히면 빈 묶음과 같은 모양이 된다. 소수 한 자리.
 */
function formatBytes(bytes: number): string {
  if (bytes >= MIB) return `${(bytes / MIB).toFixed(1)}MiB`;
  if (bytes >= KIB) return `${(bytes / KIB).toFixed(1)}KiB`;
  return `${formatCount(bytes)}B`;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}
