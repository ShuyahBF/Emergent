import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

export default function AdminContacts() {
  const [items, setItems] = useState([]);
  useEffect(() => { apiClient.get("/admin/contacts").then((r) => setItems(r.data)).catch(() => {}); }, []);
  return (
    <div className="space-y-6" data-testid="admin-contacts-page">
      <div><h1 className="text-2xl font-display font-bold">Messages reçus</h1></div>
      <div className="space-y-3">
        {items.length === 0 && <p className="text-slate-500">Aucun message.</p>}
        {items.map((c) => (
          <div key={c.id} className="rounded-xl border border-slate-200 bg-white p-5" data-testid={`contact-${c.id}`}>
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div>
                <p className="font-semibold">{c.name} <span className="text-slate-500 font-normal text-sm">— {c.email}</span></p>
                {c.subject && <p className="text-sm text-slate-700 mt-1">{c.subject}</p>}
              </div>
              <span className="text-xs text-slate-500">{new Date(c.created_at).toLocaleString("fr-FR")}</span>
            </div>
            <p className="mt-3 text-sm text-slate-600 whitespace-pre-wrap">{c.message}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
