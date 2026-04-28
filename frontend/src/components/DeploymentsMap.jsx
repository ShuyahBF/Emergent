import React, { useEffect, useMemo, useState } from "react";
import { ComposableMap, Geographies, Geography, Marker } from "@vnedyalk0v/react19-simple-maps";
import { apiClient } from "@/lib/api";
import { Globe2, MapPin } from "lucide-react";

// Country -> approx [lng, lat] centroid (curated list, fallback for popular countries).
// Used for placing the deployment marker. Add more entries as needed.
const COUNTRY_COORDS = {
  "Burkina Faso": [-1.5616, 12.2383],
  "Côte d'Ivoire": [-5.5471, 7.5400],
  "Côte d Ivoire": [-5.5471, 7.5400],
  "Cote d'Ivoire": [-5.5471, 7.5400],
  "Mali": [-3.9962, 17.5707],
  "Sénégal": [-14.4524, 14.4974],
  "Senegal": [-14.4524, 14.4974],
  "Niger": [8.0817, 17.6078],
  "Togo": [0.8248, 8.6195],
  "Bénin": [2.3158, 9.3077],
  "Benin": [2.3158, 9.3077],
  "Ghana": [-1.0232, 7.9465],
  "Nigeria": [8.6753, 9.0820],
  "Maroc": [-7.0926, 31.7917],
  "Morocco": [-7.0926, 31.7917],
  "Algérie": [1.6596, 28.0339],
  "Algeria": [1.6596, 28.0339],
  "Tunisie": [9.5375, 33.8869],
  "Tunisia": [9.5375, 33.8869],
  "Cameroun": [12.3547, 7.3697],
  "Cameroon": [12.3547, 7.3697],
  "Tchad": [18.7322, 15.4542],
  "Chad": [18.7322, 15.4542],
  "Gabon": [11.6094, -0.8037],
  "Congo": [15.8277, -0.2280],
  "RDC": [21.7587, -4.0383],
  "Kenya": [37.9062, -0.0236],
  "Éthiopie": [40.4897, 9.1450],
  "Ethiopia": [40.4897, 9.1450],
  "Afrique du Sud": [22.9375, -30.5595],
  "South Africa": [22.9375, -30.5595],
  "France": [2.2137, 46.2276],
  "Belgique": [4.4699, 50.5039],
  "Belgium": [4.4699, 50.5039],
  "Suisse": [8.2275, 46.8182],
  "Switzerland": [8.2275, 46.8182],
  "Canada": [-106.3468, 56.1304],
  "United States": [-95.7129, 37.0902],
  "USA": [-95.7129, 37.0902],
  "Brazil": [-51.9253, -14.2350],
  "Brésil": [-51.9253, -14.2350],
};

function findCoords(country) {
  if (!country) return null;
  // exact
  if (COUNTRY_COORDS[country]) return COUNTRY_COORDS[country];
  // case insensitive
  const ci = Object.keys(COUNTRY_COORDS).find((k) => k.toLowerCase() === country.toLowerCase());
  if (ci) return COUNTRY_COORDS[ci];
  // partial match
  const partial = Object.keys(COUNTRY_COORDS).find((k) => k.toLowerCase().startsWith(country.toLowerCase().slice(0, 4)));
  return partial ? COUNTRY_COORDS[partial] : null;
}

export default function DeploymentsMap() {
  const [data, setData] = useState([]);
  const [geo, setGeo] = useState(null);
  const [hovered, setHovered] = useState(null); // {country, total, solutions}
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    apiClient.get("/deployments").then((r) => setData(r.data)).catch(() => {});
    fetch("/countries-110m.json").then((r) => r.json()).then(setGeo).catch(() => {});
  }, []);

  const points = useMemo(() => {
    return data
      .map((d) => ({ ...d, coords: findCoords(d.country) }))
      .filter((d) => Array.isArray(d.coords));
  }, [data]);

  const totalCountries = data.length;
  const totalInstalls = data.reduce((s, d) => s + (d.total_installations || 0), 0);
  const totalSolutions = useMemo(() => {
    const set = new Set();
    data.forEach((d) => d.solutions.forEach((s) => set.add(s.name)));
    return set.size;
  }, [data]);

  const radius = (n) => Math.min(18, 4 + Math.sqrt(Math.max(1, n)) * 1.6);

  return (
    <section className="relative bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 text-white py-20 sm:py-24" data-testid="deployments-section">
      <div className="absolute inset-0 opacity-[0.07] pointer-events-none"
           style={{ backgroundImage: "radial-gradient(circle at 30% 30%, #1E90FF 0%, transparent 60%)" }} />
      <div className="relative max-w-7xl mx-auto px-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-[0.3em] text-sawali-blue mb-3">
          <Globe2 className="h-4 w-4" /> Déploiements à travers le monde
        </div>
        <div className="flex items-end justify-between flex-wrap gap-6 mb-10">
          <h2 className="text-4xl sm:text-5xl font-display font-bold tracking-tight max-w-2xl">
            Nos solutions, déjà <span className="text-sawali-blue">déployées sur 3 continents</span>.
          </h2>
          <div className="flex gap-6 text-sm">
            <div><p className="text-3xl font-display font-bold">{totalInstalls}</p><p className="text-slate-400 text-xs uppercase tracking-widest">Installations</p></div>
            <div><p className="text-3xl font-display font-bold">{totalCountries}</p><p className="text-slate-400 text-xs uppercase tracking-widest">Pays</p></div>
            <div><p className="text-3xl font-display font-bold">{totalSolutions}</p><p className="text-slate-400 text-xs uppercase tracking-widest">Solutions</p></div>
          </div>
        </div>

        <div className="relative rounded-2xl border border-white/10 bg-slate-900/40 backdrop-blur p-2 sm:p-4" data-testid="deployments-map-container">
          <ComposableMap
            projectionConfig={{ rotate: [-10, 0, 0], scale: 145 }}
            style={{ width: "100%", height: "auto" }}
          >
            <Geographies geography={geo}>
              {({ geographies }) =>
                geographies.map((g) => (
                  <Geography
                    key={g.rsmKey}
                    geography={g}
                    style={{
                      default: { fill: "#1e293b", stroke: "#334155", strokeWidth: 0.4, outline: "none" },
                      hover: { fill: "#334155", outline: "none" },
                      pressed: { fill: "#334155", outline: "none" },
                    }}
                  />
                ))
              }
            </Geographies>

            {points.map((p) => (
              <Marker
                key={p.country}
                coordinates={p.coords}
                onMouseEnter={(e) => {
                  setHovered({ country: p.country, total: p.total_installations, solutions: p.solutions });
                  setTooltipPos({ x: e.clientX, y: e.clientY });
                }}
                onMouseMove={(e) => setTooltipPos({ x: e.clientX, y: e.clientY })}
                onMouseLeave={() => setHovered(null)}
              >
                <circle r={radius(p.total_installations)} fill="#1E90FF" fillOpacity={0.4} stroke="#1E90FF" strokeWidth={1.2} className="cursor-pointer transition-all hover:fill-opacity-70" data-testid={`deployment-marker-${p.country}`} />
                <circle r={3} fill="#fff" />
              </Marker>
            ))}
          </ComposableMap>

          {/* List of countries below the map */}
          {points.length > 0 && (
            <div className="mt-4 px-2 pb-2 grid sm:grid-cols-2 lg:grid-cols-3 gap-2 text-sm">
              {points.map((p) => (
                <div key={p.country} className="flex items-center justify-between rounded-md border border-white/10 bg-slate-900/60 px-3 py-2" data-testid={`deployment-tile-${p.country}`}>
                  <span className="inline-flex items-center gap-2 text-slate-200"><MapPin className="h-3.5 w-3.5 text-sawali-blue" />{p.country}</span>
                  <span className="text-xs text-slate-400">
                    {p.solutions.map((s) => `${s.name}: ${s.installations}`).join(" · ")}
                  </span>
                </div>
              ))}
            </div>
          )}
          {points.length === 0 && (
            <p className="text-center text-slate-400 py-8 text-sm">
              Bientôt : la carte de nos déploiements à travers l'Afrique et le monde.
            </p>
          )}
        </div>

        {/* Hover tooltip (positioned in viewport coordinates) */}
        {hovered && (
          <div
            className="fixed z-50 rounded-lg border border-sawali-blue/40 bg-slate-900/95 backdrop-blur px-3 py-2 text-xs text-white shadow-2xl pointer-events-none"
            style={{ left: tooltipPos.x + 12, top: tooltipPos.y + 12, maxWidth: 260 }}
          >
            <p className="font-display font-semibold text-sm text-sawali-blue">{hovered.country}</p>
            <p className="text-slate-300 mb-1">Total : {hovered.total} installation{hovered.total > 1 ? "s" : ""}</p>
            <ul className="space-y-0.5">
              {hovered.solutions.map((s) => (
                <li key={s.name} className="flex justify-between gap-3">
                  <span>{s.name}{s.city ? ` — ${s.city}` : ""}</span>
                  <span className="font-mono text-sawali-blue">{s.installations}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
