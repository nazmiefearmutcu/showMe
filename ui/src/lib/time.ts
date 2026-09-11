export function relativeTimeLabel(value: string | null | undefined, nowMs = Date.now()): string | null {
  const raw = String(value ?? "").trim();
  if (!raw) return null;

  const normalized = normalizeRelativeInput(raw);
  if (normalized) return normalized;

  const date = parseNewsDate(raw);
  if (date == null) return raw;

  const diffMs = Math.max(0, nowMs - date.getTime());
  return diffMsToEnglish(diffMs);
}

export function newsTimestampMs(value: string | null | undefined, nowMs = Date.now()): number | null {
  const raw = String(value ?? "").trim();
  if (!raw) return null;

  const relativeMs = relativeInputToMs(raw, nowMs);
  if (relativeMs != null) return relativeMs;

  const date = parseNewsDate(raw);
  return date?.getTime() ?? null;
}

export function sortNewsNewestFirst<T>(rows: T[], getTime: (row: T) => string | null | undefined): T[] {
  return rows
    .map((row, index) => ({ row, index, ts: newsTimestampMs(getTime(row)) }))
    .sort((a, b) => {
      const ats = a.ts ?? Number.NEGATIVE_INFINITY;
      const bts = b.ts ?? Number.NEGATIVE_INFINITY;
      if (ats !== bts) return bts - ats;
      return a.index - b.index;
    })
    .map(({ row }) => row);
}

function parseNewsDate(value: string): Date | null {
  const trimmed = value.trim();
  const dateOnly = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateOnly) {
    const [, year, month, day] = dateOnly;
    return new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  }
  const date = new Date(trimmed);
  return Number.isNaN(date.getTime()) ? null : date;
}

function normalizeRelativeInput(value: string): string | null {
  const lowered = value.trim().toLowerCase();
  if (["now", "just now", "az once", "az önce"].includes(lowered)) return "just now";

  const match = lowered.match(
    /^(\d+)\s*(s|sec|secs|second|seconds|sn|m|min|mins|minute|minutes|dk|dakika|h|hr|hrs|hour|hours|saat|d|day|days|gün|gun|w|week|weeks|hafta|mo|month|months|ay|y|yr|year|years|yıl|yil)(?:\s*(ago|once|önce))?$/,
  );
  if (!match) return null;

  const amount = Math.max(0, Number(match[1]));
  const unit = match[2];
  if (["s", "sec", "secs", "second", "seconds", "sn"].includes(unit)) return "just now";
  if (["m", "min", "mins", "minute", "minutes", "dk", "dakika"].includes(unit)) {
    return `${Math.max(1, amount)} minutes ago`;
  }
  if (["h", "hr", "hrs", "hour", "hours", "saat"].includes(unit)) {
    return `${Math.max(1, amount)} hours ago`;
  }
  if (["d", "day", "days", "gün", "gun"].includes(unit)) {
    return `${Math.max(1, amount)} days ago`;
  }
  if (["w", "week", "weeks", "hafta"].includes(unit)) {
    return `${Math.max(1, amount)} weeks ago`;
  }
  if (["mo", "month", "months", "ay"].includes(unit)) {
    return `${Math.max(1, amount)} months ago`;
  }
  return `${Math.max(1, amount)} years ago`;
}

function relativeInputToMs(value: string, nowMs: number): number | null {
  const lowered = value.trim().toLowerCase();
  if (["now", "just now", "az once", "az önce"].includes(lowered)) return nowMs;

  const match = lowered.match(
    /^(\d+)\s*(s|sec|secs|second|seconds|sn|m|min|mins|minute|minutes|dk|dakika|h|hr|hrs|hour|hours|saat|d|day|days|gün|gun|w|week|weeks|hafta|mo|month|months|ay|y|yr|year|years|yıl|yil)(?:\s*(ago|once|önce))?$/,
  );
  if (!match) return null;

  const amount = Math.max(0, Number(match[1]));
  const unit = match[2];
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const multipliers: Record<string, number> = {
    s: 1000,
    sec: 1000,
    secs: 1000,
    second: 1000,
    seconds: 1000,
    sn: 1000,
    m: minute,
    min: minute,
    mins: minute,
    minute,
    minutes: minute,
    dk: minute,
    dakika: minute,
    h: hour,
    hr: hour,
    hrs: hour,
    hour,
    hours: hour,
    saat: hour,
    d: day,
    day,
    days: day,
    gun: day,
    "gün": day,
    w: 7 * day,
    week: 7 * day,
    weeks: 7 * day,
    hafta: 7 * day,
    mo: 30 * day,
    month: 30 * day,
    months: 30 * day,
    ay: 30 * day,
    y: 365 * day,
    yr: 365 * day,
    year: 365 * day,
    years: 365 * day,
    yil: 365 * day,
    "yıl": 365 * day,
  };
  return nowMs - amount * (multipliers[unit] ?? day);
}

function diffMsToEnglish(diffMs: number): string {
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const month = 30 * day;
  const year = 365 * day;

  if (diffMs < minute) return "just now";
  if (diffMs < hour) return `${Math.max(1, Math.floor(diffMs / minute))} minutes ago`;
  if (diffMs < day) return `${Math.max(1, Math.floor(diffMs / hour))} hours ago`;
  if (diffMs < month) return `${Math.max(1, Math.floor(diffMs / day))} days ago`;
  if (diffMs < year) return `${Math.max(1, Math.floor(diffMs / month))} months ago`;
  return `${Math.max(1, Math.floor(diffMs / year))} years ago`;
}
