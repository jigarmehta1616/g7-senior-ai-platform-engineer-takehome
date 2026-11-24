import { useState, type FormEvent } from "react";

import { api } from "../../api/client";
import { useToast } from "../../app/useToast";
import { Button, Field } from "../../components";
import type { CustomerSummary } from "../../types/api";
import { CustomerCard } from "./CustomerCard";

export function CustomerPage() {
  const toast = useToast();
  const [id, setId] = useState("ACC-007");
  const [customer, setCustomer] = useState<CustomerSummary | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async (e: FormEvent) => {
    e.preventDefault();
    const accountId = id.trim();
    if (!accountId || loading) return;
    setLoading(true);
    try {
      setCustomer((await api.getCustomer(accountId)).data);
    } catch (error) {
      setCustomer(null);
      toast.fail(error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <form onSubmit={(e) => void load(e)} className="flex items-end gap-3">
        <Field label="Account id">
          <input required pattern="[A-Za-z0-9][A-Za-z0-9_\-]{1,31}" value={id} onChange={(e) => { setId(e.target.value); }} />
        </Field>
        <Button type="submit" disabled={loading || !id.trim()}>{loading ? "Loading…" : "Load"}</Button>
      </form>
      {customer && <CustomerCard customer={customer} />}
    </div>
  );
}
