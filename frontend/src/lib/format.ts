const numberFormat = new Intl.NumberFormat();

/** "pending_customer" -> "pending customer" */
export const humanize = (value: string): string => value.replaceAll("_", " ");

export const formatNumber = (value: number): string => numberFormat.format(value);

export const formatCurrency = (value: number): string => `$${numberFormat.format(value)}`;

export const formatDateTime = (iso: string): string => new Date(iso).toLocaleString();

export const formatTime = (iso: string): string => new Date(iso).toLocaleTimeString();

export const formatHours = (hours: number): string => `${String(Math.round(hours))}h`;
