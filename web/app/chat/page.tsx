"use client";
import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { TicketResult } from "@/lib/schemas";
import { useRequireSession } from "@/lib/useSession";
import { btnPrimary, ErrorNote, input, PageHeader } from "@/components/ui";

type Turn = { from: "customer" | "agent"; text: string; proposalId?: string | null };

export default function ChatPage() {
  const session = useRequireSession();
  const [customer, setCustomer] = useState("wanjiku");
  const [text, setText] = useState("nimekatwa mara mbili KES 1,200 Java House");
  const [turns, setTurns] = useState<Turn[]>([]);
  const canSend = session?.role === "agent" || session?.role === "admin";

  const send = useMutation({
    mutationFn: (message: string) => api(TicketResult, "/tickets", { method: "POST", body: { customer_ref: customer, message } }),
    onSuccess: (r, message) =>
      setTurns((t) => [
        ...t,
        { from: "customer", text: message },
        {
          from: "agent",
          text:
            r.decision === "review" ? "Thanks — I've asked a colleague to review this refund and will update you."
            : r.decision === "escalated" ? "Thanks — I've passed this to a human agent."
            : r.reply ?? "Done.",
          proposalId: r.proposal_id,
        },
      ]),
  });

  const SAMPLES = [
    "nimekatwa mara mbili KES 1,200 Java House",
    "Refund please, I was charged for an order I cancelled",
    "wapi pesa yangu? sijapata refund",
  ];
  const clock = (i: number) => String(i);

  return (
    <>
      <PageHeader title="Chat simulator" sub="The single channel: a customer message becomes a ticket and the agent drafts a proposal. Sign in as agent to send." />
      <div className="mx-auto flex h-[70vh] max-w-2xl flex-col overflow-hidden rounded-lg border border-line bg-surface">
        <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
          <span aria-hidden className="grid size-8 place-items-center rounded-full bg-sunken text-sm font-medium uppercase">{customer[0]}</span>
          <div>
            <div className="text-sm font-medium capitalize">{customer}</div>
            <div className="text-xs text-muted">Customer · support chat</div>
          </div>
          <select aria-label="Customer" className={`${input} ml-auto`} value={customer} onChange={(e) => setCustomer(e.target.value)}>
            <option>wanjiku</option><option>otieno</option>
          </select>
        </div>
        <div className="flex-1 space-y-2 overflow-y-auto bg-sunken/40 p-4">
          {turns.length === 0 && <p className="pt-16 text-center text-sm text-muted">No messages yet. Pick a sample below or type your own.</p>}
          {turns.map((t, i) => (
            <div key={i} data-turn={clock(i)} className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm ${t.from === "customer" ? "rounded-bl-sm bg-surface" : "ml-auto rounded-br-sm bg-accent text-accent-ink"}`}>
              {t.text}
              {t.proposalId && (
                <div className="mt-1 text-xs"><Link className="underline" href={`/proposals/${t.proposalId}`}>View proposal</Link></div>
              )}
            </div>
          ))}
        </div>
        <div className="space-y-2 border-t border-line p-3">
          <ErrorNote error={send.error} />
          <div className="flex flex-wrap gap-1.5">
            {SAMPLES.map((m) => (
              <button key={m} type="button" className="rounded-full border border-line px-2.5 py-1 text-xs text-muted hover:bg-sunken" onClick={() => setText(m)}>{m}</button>
            ))}
          </div>
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); send.mutate(text); }}>
            <input aria-label="Message" className={`${input} flex-1`} value={text} onChange={(e) => setText(e.target.value)} />
            <button className={btnPrimary} disabled={!canSend || send.isPending || !text.trim()}>Send</button>
          </form>
          {!canSend && <p className="text-xs text-[color:var(--s-pending)]">Your role cannot create tickets.</p>}
        </div>
      </div>
    </>
  );
}
