"use client";
import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { TicketResult } from "@/lib/schemas";
import { useRequireSession } from "@/lib/useSession";
import { btnPrimary, Card, ErrorNote, input } from "@/components/ui";

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

  return (
    <>
      <h1 className="text-xl font-semibold">Chat simulator</h1>
      <p className="text-sm text-zinc-500">The single channel: a customer message becomes a ticket and the agent drafts a proposal. Sign in as <b>agent</b> to send.</p>
      <Card>
        <div className="mb-4 space-y-2">
          {turns.map((t, i) => (
            <div key={i} className={`max-w-md rounded-lg px-3 py-2 text-sm ${t.from === "customer" ? "bg-emerald-100" : "ml-auto bg-zinc-100"}`}>
              {t.text}
              {t.proposalId && (
                <div className="mt-1 text-xs"><Link className="underline" href={`/proposals/${t.proposalId}`}>View proposal</Link></div>
              )}
            </div>
          ))}
        </div>
        <ErrorNote error={send.error} />
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); send.mutate(text); }}>
          <select aria-label="Customer" className={input} value={customer} onChange={(e) => setCustomer(e.target.value)}>
            <option>wanjiku</option><option>otieno</option>
          </select>
          <input aria-label="Message" className={`${input} flex-1`} value={text} onChange={(e) => setText(e.target.value)} />
          <button className={btnPrimary} disabled={!canSend || send.isPending || !text.trim()}>Send</button>
        </form>
        {!canSend && <p className="mt-2 text-xs text-amber-700">Your role cannot create tickets.</p>}
      </Card>
    </>
  );
}
