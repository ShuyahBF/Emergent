// AdminSyntheseSupport.jsx — Lot 92 : page « Synthèse du support » (administrateur et superviseur).
// Demandes non répondues, totaux de la période et demandes transmises à Claude (voir components/SyntheseSupport).
import React from "react";
import SyntheseSupport from "@/components/SyntheseSupport";

export default function AdminSyntheseSupport() {
  return (
    <div className="space-y-4 p-4 md:p-6">
      <div>
        <h1 className="font-display text-xl font-bold">Synthèse du support</h1>
        <p className="text-sm text-slate-600">
          Demandes du Support Loois et des plateformes web (sTer, adLyn, beAuthentik, bfmobility, ALBARKA) qui attendent
          une réponse, totaux de la période et demandes de fonctionnalités transmises à Claude.
        </p>
      </div>
      <SyntheseSupport />
    </div>
  );
}
