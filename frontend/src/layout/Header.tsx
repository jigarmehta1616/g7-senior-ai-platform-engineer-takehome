import { useSession } from "../app/useSession";
import { useToast } from "../app/useToast";

export function Header() {
  const { personas, persona, scopes, signIn } = useSession();
  const toast = useToast();

  const switchPersona = (id: string) => {
    signIn(id).catch((error: unknown) => {
      toast.fail(error); // the previous user stays signed in
    });
  };

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3">
      <div className="font-semibold">
        Support Console <span className="ml-1 rounded bg-canvas px-1.5 py-0.5 text-xs font-semibold text-muted uppercase">local</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="persona" className="text-xs text-muted">Signed in as</label>
        <select id="persona" value={persona ?? ""} disabled={personas.length === 0} onChange={(e) => { switchPersona(e.target.value); }}>
          {personas.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <div className="flex flex-wrap gap-1">
          {scopes.map((s) => (
            <span key={s} className="rounded-full bg-canvas px-2 py-0.5 text-xs text-muted">{s}</span>
          ))}
        </div>
      </div>
    </header>
  );
}
