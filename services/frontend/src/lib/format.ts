export function formatCurrencyEGP(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }

  return new Intl.NumberFormat("en-EG", {
    style: "currency",
    currency: "EGP",
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatPercent(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }

  return `${(value * 100).toFixed(2)}%`;
}

export function formatDateTime(value?: string) {
  if (!value) {
    return "-";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en-EG", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
