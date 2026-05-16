import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(value?: string | number | null) {
  if (!value) {
    return "未记录";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function firstValue<T>(items: T[] | undefined): T | undefined {
  return items?.[0];
}

export function toNumberId(value: string | undefined) {
  const id = Number(value);
  return Number.isFinite(id) && id > 0 ? id : 0;
}

export function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "请求失败";
}
