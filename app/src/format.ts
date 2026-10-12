import type { DriveInfo, EngineErrorDetail, Progress } from "./shared/protocol";

const KB = 1024, MB = KB ** 2, GB = KB ** 3, TB = KB ** 4;

export function human(bytes: number | null | undefined): string {
  if (bytes == null) return "?";
  if (bytes >= TB) return `${(bytes / TB).toFixed(2)} TB`;
  if (bytes >= GB) return `${(bytes / GB).toFixed(2)} GB`;
  if (bytes >= MB) return `${(bytes / MB).toFixed(1)} MB`;
  return `${Math.round(bytes / KB)} KB`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return "";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

export function percent(p: Progress | null): number {
  return p && p.total ? Math.min(100, (100 * p.done) / p.total) : 0;
}

export function progressText(p: Progress): string {
  const parts = [p.unit === "bytes" ? `${human(p.done)} of ${human(p.total)}` : `${p.done} of ${p.total}`];
  if (p.rate) parts.push(`${(p.rate / MB).toFixed(1)} MB/s`);
  if (p.eta != null) parts.push(`about ${duration(p.eta)} left`);
  return parts.join(" · ");
}

export function driveLabel(d: DriveInfo): string {
  const name = d.model || "Unknown drive";
  return `${name} — ${human(d.size)}`;
}

/** A sentence a non-expert can act on. */
export function explainError(e: unknown, platform: string): string {
  const d = (e ?? {}) as Partial<EngineErrorDetail>;
  switch (d.type) {
    case "AccessDenied":
      return platform === "win32"
        ? "Reading drives needs Administrator rights. Close Disk Salvage, right-click it and choose \"Run as administrator\". Image files work without it."
        : "Reading drives needs root rights. Start Disk Salvage with sudo. Image files work without it.";
    case "SameDriveError":
    case "OutOfSpace":
    case "SourceUnavailable":
    case "ImageMismatch":
      return d.message ?? d.type;
    case "EngineStopped":
      return `The recovery engine stopped unexpectedly. ${d.message ?? ""}`;
    default:
      return d.message ?? String(e);
  }
}
