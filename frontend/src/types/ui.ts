import type { ButtonHTMLAttributes, ComponentType, ReactNode } from "react";

import type { Priority } from "./api";

export type Tone = "neutral" | "ok" | "warn" | "bad";
export type ButtonVariant = "primary" | "ghost" | "danger";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export interface BadgeProps {
  tone?: Tone;
  children: ReactNode;
}

export interface CardProps {
  children: ReactNode;
  className?: string;
}

export interface KpiProps {
  label: string;
  children: ReactNode;
}

export interface FieldProps {
  label: string;
  children: ReactNode;
}

export interface LockedProps {
  scope: string;
}

export interface PriorityLabelProps {
  priority: Priority;
}

export interface AlertProps {
  tone?: Exclude<Tone, "neutral">;
  children: ReactNode;
}

/** One column of a DataTable: a header and how to render a cell for a row. */
export interface Column<T> {
  header: string;
  cell: (row: T) => ReactNode;
  className?: string;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  empty?: string;
}

export interface DrawerProps {
  label: string;
  onClose: () => void;
  children: ReactNode;
}

export interface TabItem<Id extends string> {
  id: Id;
  label: string;
  Page: ComponentType;
}

export interface TabsProps<Id extends string> {
  tabs: readonly TabItem<Id>[];
  active: Id;
  onChange: (id: Id) => void;
}

export interface ErrorBoundaryProps {
  children: ReactNode;
}

export interface ErrorBoundaryState {
  /** Message of the error that broke rendering, or null when healthy. */
  error: string | null;
}
