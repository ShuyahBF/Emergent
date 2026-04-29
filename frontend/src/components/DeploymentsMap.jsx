import React, { useEffect, useMemo, useState } from "react";
import { ComposableMap, Geographies, Geography, Marker } from "@vnedyalk0v/react19-simple-maps";
import { apiClient } from "@/lib/api";
import { Globe2, MapPin, X, Calendar } from "lucide-react";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip as RechartsTooltip, CartesianGrid } from "recharts";

// Country -> approx [lng, lat] centroid. Curated worldwide list. Add aliases (FR/EN) for matching.
const COUNTRY_COORDS = {
  // ==== Afrique ====
  "Algérie": [1.66, 28.03], "Algeria": [1.66, 28.03],
  "Angola": [17.87, -11.20],
  "Bénin": [2.32, 9.31], "Benin": [2.32, 9.31],
  "Botswana": [24.68, -22.33],
  "Burkina Faso": [-1.56, 12.24],
  "Burundi": [29.92, -3.37],
  "Cameroun": [12.35, 7.37], "Cameroon": [12.35, 7.37],
  "Cap-Vert": [-23.51, 16.00], "Cape Verde": [-23.51, 16.00],
  "Centrafrique": [20.94, 6.61], "Central African Republic": [20.94, 6.61],
  "Tchad": [18.73, 15.45], "Chad": [18.73, 15.45],
  "Comores": [43.87, -11.65], "Comoros": [43.87, -11.65],
  "Congo": [15.83, -0.23], "République du Congo": [15.83, -0.23],
  "RDC": [21.76, -4.04], "République démocratique du Congo": [21.76, -4.04], "DRC": [21.76, -4.04],
  "Côte d'Ivoire": [-5.55, 7.54], "Côte d Ivoire": [-5.55, 7.54], "Cote d'Ivoire": [-5.55, 7.54],
  "Djibouti": [42.59, 11.83],
  "Égypte": [30.80, 26.82], "Egypt": [30.80, 26.82],
  "Guinée équatoriale": [10.27, 1.65], "Equatorial Guinea": [10.27, 1.65],
  "Érythrée": [39.78, 15.18], "Eritrea": [39.78, 15.18],
  "Eswatini": [31.47, -26.52], "Swaziland": [31.47, -26.52],
  "Éthiopie": [40.49, 9.15], "Ethiopia": [40.49, 9.15],
  "Gabon": [11.61, -0.80],
  "Gambie": [-15.31, 13.44], "Gambia": [-15.31, 13.44],
  "Ghana": [-1.02, 7.95],
  "Guinée": [-9.70, 9.95], "Guinea": [-9.70, 9.95],
  "Guinée-Bissau": [-15.18, 11.80], "Guinea-Bissau": [-15.18, 11.80],
  "Kenya": [37.91, -0.02],
  "Lesotho": [28.23, -29.61],
  "Liberia": [-9.43, 6.43], "Libéria": [-9.43, 6.43],
  "Libye": [17.23, 26.34], "Libya": [17.23, 26.34],
  "Madagascar": [46.87, -18.77],
  "Malawi": [34.30, -13.25],
  "Mali": [-3.99, 17.57],
  "Mauritanie": [-10.94, 21.00], "Mauritania": [-10.94, 21.00],
  "Maurice": [57.55, -20.35], "Mauritius": [57.55, -20.35],
  "Maroc": [-7.09, 31.79], "Morocco": [-7.09, 31.79],
  "Mozambique": [35.53, -18.67],
  "Namibie": [18.49, -22.96], "Namibia": [18.49, -22.96],
  "Niger": [8.08, 17.61],
  "Nigeria": [8.68, 9.08], "Nigéria": [8.68, 9.08],
  "Rwanda": [29.87, -1.94],
  "São Tomé-et-Príncipe": [6.61, 0.19], "Sao Tome and Principe": [6.61, 0.19],
  "Sénégal": [-14.45, 14.50], "Senegal": [-14.45, 14.50],
  "Seychelles": [55.49, -4.68],
  "Sierra Leone": [-11.78, 8.46],
  "Somalie": [46.20, 5.15], "Somalia": [46.20, 5.15],
  "Afrique du Sud": [22.94, -30.56], "South Africa": [22.94, -30.56],
  "Soudan du Sud": [31.31, 6.88], "South Sudan": [31.31, 6.88],
  "Soudan": [30.22, 12.86], "Sudan": [30.22, 12.86],
  "Tanzanie": [34.89, -6.37], "Tanzania": [34.89, -6.37],
  "Togo": [0.82, 8.62],
  "Tunisie": [9.54, 33.89], "Tunisia": [9.54, 33.89],
  "Ouganda": [32.29, 1.37], "Uganda": [32.29, 1.37],
  "Zambie": [27.85, -13.13], "Zambia": [27.85, -13.13],
  "Zimbabwe": [29.15, -19.02],

  // ==== Europe ====
  "Albanie": [20.17, 41.15], "Albania": [20.17, 41.15],
  "Allemagne": [10.45, 51.17], "Germany": [10.45, 51.17],
  "Autriche": [14.55, 47.52], "Austria": [14.55, 47.52],
  "Belgique": [4.47, 50.50], "Belgium": [4.47, 50.50],
  "Biélorussie": [27.95, 53.71], "Belarus": [27.95, 53.71],
  "Bosnie": [17.68, 43.92], "Bosnia and Herzegovina": [17.68, 43.92],
  "Bulgarie": [25.49, 42.73], "Bulgaria": [25.49, 42.73],
  "Croatie": [15.20, 45.10], "Croatia": [15.20, 45.10],
  "Chypre": [33.43, 35.13], "Cyprus": [33.43, 35.13],
  "Tchéquie": [15.47, 49.82], "Czech Republic": [15.47, 49.82], "Czechia": [15.47, 49.82],
  "Danemark": [9.50, 56.26], "Denmark": [9.50, 56.26],
  "Estonie": [25.01, 58.60], "Estonia": [25.01, 58.60],
  "Finlande": [25.75, 61.92], "Finland": [25.75, 61.92],
  "France": [2.21, 46.23],
  "Grèce": [21.82, 39.07], "Greece": [21.82, 39.07],
  "Hongrie": [19.50, 47.16], "Hungary": [19.50, 47.16],
  "Islande": [-19.02, 64.96], "Iceland": [-19.02, 64.96],
  "Irlande": [-8.24, 53.41], "Ireland": [-8.24, 53.41],
  "Italie": [12.57, 41.87], "Italy": [12.57, 41.87],
  "Lettonie": [24.60, 56.88], "Latvia": [24.60, 56.88],
  "Lituanie": [23.88, 55.17], "Lithuania": [23.88, 55.17],
  "Luxembourg": [6.13, 49.82],
  "Malte": [14.38, 35.94], "Malta": [14.38, 35.94],
  "Moldavie": [28.37, 47.41], "Moldova": [28.37, 47.41],
  "Monaco": [7.41, 43.74],
  "Pays-Bas": [5.29, 52.13], "Netherlands": [5.29, 52.13],
  "Macédoine du Nord": [21.74, 41.61], "North Macedonia": [21.74, 41.61],
  "Norvège": [8.47, 60.47], "Norway": [8.47, 60.47],
  "Pologne": [19.15, 51.92], "Poland": [19.15, 51.92],
  "Portugal": [-8.22, 39.40],
  "Roumanie": [24.97, 45.94], "Romania": [24.97, 45.94],
  "Russie": [105.32, 61.52], "Russia": [105.32, 61.52],
  "Serbie": [21.01, 44.02], "Serbia": [21.01, 44.02],
  "Slovaquie": [19.70, 48.67], "Slovakia": [19.70, 48.67],
  "Slovénie": [14.99, 46.15], "Slovenia": [14.99, 46.15],
  "Espagne": [-3.75, 40.46], "Spain": [-3.75, 40.46],
  "Suède": [18.64, 60.13], "Sweden": [18.64, 60.13],
  "Suisse": [8.23, 46.82], "Switzerland": [8.23, 46.82],
  "Turquie": [35.24, 38.96], "Turkey": [35.24, 38.96],
  "Ukraine": [31.17, 48.38],
  "Royaume-Uni": [-3.44, 55.38], "United Kingdom": [-3.44, 55.38], "UK": [-3.44, 55.38],
  "Vatican": [12.45, 41.90],

  // ==== Amérique du Nord & Centrale & Caraïbes ====
  "Canada": [-106.35, 56.13],
  "Mexique": [-102.55, 23.63], "Mexico": [-102.55, 23.63],
  "États-Unis": [-95.71, 37.09], "United States": [-95.71, 37.09], "USA": [-95.71, 37.09],
  "Cuba": [-77.78, 21.52],
  "République dominicaine": [-70.16, 18.74], "Dominican Republic": [-70.16, 18.74],
  "Haïti": [-72.29, 18.97], "Haiti": [-72.29, 18.97],
  "Jamaïque": [-77.30, 18.11], "Jamaica": [-77.30, 18.11],
  "Bahamas": [-77.40, 25.03],
  "Trinité-et-Tobago": [-61.22, 10.69], "Trinidad and Tobago": [-61.22, 10.69],
  "Guatemala": [-90.23, 15.78],
  "Honduras": [-86.24, 15.20],
  "Salvador": [-88.90, 13.79], "El Salvador": [-88.90, 13.79],
  "Nicaragua": [-85.21, 12.86],
  "Costa Rica": [-83.75, 9.75],
  "Panama": [-80.78, 8.54],
  "Belize": [-88.50, 17.19],

  // ==== Amérique du Sud ====
  "Argentine": [-63.62, -38.42], "Argentina": [-63.62, -38.42],
  "Bolivie": [-63.59, -16.29], "Bolivia": [-63.59, -16.29],
  "Brésil": [-51.93, -14.24], "Brazil": [-51.93, -14.24],
  "Chili": [-71.54, -35.68], "Chile": [-71.54, -35.68],
  "Colombie": [-74.30, 4.57], "Colombia": [-74.30, 4.57],
  "Équateur": [-78.18, -1.83], "Ecuador": [-78.18, -1.83],
  "Guyana": [-58.93, 4.86], "Guyane": [-58.93, 4.86],
  "Paraguay": [-58.44, -23.44],
  "Pérou": [-75.02, -9.19], "Peru": [-75.02, -9.19],
  "Suriname": [-56.03, 3.92],
  "Uruguay": [-55.77, -32.52],
  "Venezuela": [-66.59, 6.42],

  // ==== Asie ====
  "Afghanistan": [67.71, 33.94],
  "Arménie": [45.04, 40.07], "Armenia": [45.04, 40.07],
  "Azerbaïdjan": [47.58, 40.14], "Azerbaijan": [47.58, 40.14],
  "Bahreïn": [50.55, 26.07], "Bahrain": [50.55, 26.07],
  "Bangladesh": [90.36, 23.68],
  "Bhoutan": [90.43, 27.51], "Bhutan": [90.43, 27.51],
  "Brunei": [114.73, 4.54],
  "Cambodge": [104.99, 12.57], "Cambodia": [104.99, 12.57],
  "Chine": [104.20, 35.86], "China": [104.20, 35.86],
  "Géorgie": [43.36, 42.32], "Georgia": [43.36, 42.32],
  "Inde": [78.96, 20.59], "India": [78.96, 20.59],
  "Indonésie": [113.92, -0.79], "Indonesia": [113.92, -0.79],
  "Iran": [53.69, 32.43],
  "Iraq": [43.68, 33.22], "Irak": [43.68, 33.22],
  "Israël": [34.85, 31.05], "Israel": [34.85, 31.05],
  "Japon": [138.25, 36.20], "Japan": [138.25, 36.20],
  "Jordanie": [36.24, 30.59], "Jordan": [36.24, 30.59],
  "Kazakhstan": [66.92, 48.02],
  "Corée du Nord": [127.51, 40.34], "North Korea": [127.51, 40.34],
  "Corée du Sud": [127.77, 35.91], "South Korea": [127.77, 35.91],
  "Koweït": [47.48, 29.31], "Kuwait": [47.48, 29.31],
  "Kirghizistan": [74.77, 41.20], "Kyrgyzstan": [74.77, 41.20],
  "Laos": [102.50, 19.86],
  "Liban": [35.86, 33.85], "Lebanon": [35.86, 33.85],
  "Malaisie": [101.98, 4.21], "Malaysia": [101.98, 4.21],
  "Maldives": [73.22, 3.20],
  "Mongolie": [103.85, 46.86], "Mongolia": [103.85, 46.86],
  "Myanmar": [95.96, 21.91], "Birmanie": [95.96, 21.91],
  "Népal": [84.12, 28.39], "Nepal": [84.12, 28.39],
  "Oman": [55.92, 21.51],
  "Pakistan": [69.35, 30.38],
  "Palestine": [35.23, 31.95],
  "Philippines": [121.77, 12.88],
  "Qatar": [51.18, 25.35],
  "Arabie saoudite": [45.08, 23.89], "Saudi Arabia": [45.08, 23.89],
  "Singapour": [103.82, 1.35], "Singapore": [103.82, 1.35],
  "Sri Lanka": [80.77, 7.87],
  "Syrie": [38.99, 34.80], "Syria": [38.99, 34.80],
  "Taïwan": [120.96, 23.70], "Taiwan": [120.96, 23.70],
  "Tadjikistan": [71.28, 38.86], "Tajikistan": [71.28, 38.86],
  "Thaïlande": [100.99, 15.87], "Thailand": [100.99, 15.87],
  "Timor oriental": [125.73, -8.87], "Timor-Leste": [125.73, -8.87],
  "Turkménistan": [59.56, 38.97], "Turkmenistan": [59.56, 38.97],
  "Émirats arabes unis": [53.85, 23.42], "United Arab Emirates": [53.85, 23.42], "UAE": [53.85, 23.42],
  "Ouzbékistan": [64.59, 41.38], "Uzbekistan": [64.59, 41.38],
  "Vietnam": [108.28, 14.06], "Viêt Nam": [108.28, 14.06],
  "Yémen": [48.52, 15.55], "Yemen": [48.52, 15.55],

  // ==== Océanie ====
  "Australie": [133.78, -25.27], "Australia": [133.78, -25.27],
  "Fidji": [179.41, -16.58], "Fiji": [179.41, -16.58],
  "Nouvelle-Zélande": [174.89, -40.90], "New Zealand": [174.89, -40.90],
  "Papouasie-Nouvelle-Guinée": [143.96, -6.31], "Papua New Guinea": [143.96, -6.31],
  "Samoa": [-172.10, -13.76],
  "Tonga": [-175.20, -21.18],
  "Vanuatu": [166.96, -15.38],
};

function findCoords(country) {
  if (!country) return null;
  if (COUNTRY_COORDS[country]) return COUNTRY_COORDS[country];
  const ci = Object.keys(COUNTRY_COORDS).find((k) => k.toLowerCase() === country.toLowerCase());
  if (ci) return COUNTRY_COORDS[ci];
  // Fallback : strip accents and compare
  const norm = (s) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const ni = Object.keys(COUNTRY_COORDS).find((k) => norm(k) === norm(country));
  return ni ? COUNTRY_COORDS[ni] : null;
}

export default function DeploymentsMap() {
  const [data, setData] = useState([]);
  const [geo, setGeo] = useState(null);
  const [hovered, setHovered] = useState(null); // {country, total, solutions}
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
  const [selected, setSelected] = useState(null); // detailed modal: country object
  const [solutionFilter, setSolutionFilter] = useState("all");

  useEffect(() => {
    apiClient.get("/deployments").then((r) => setData(r.data)).catch(() => {});
    fetch("/countries-110m.json").then((r) => r.json()).then(setGeo).catch(() => {});
  }, []);

  // Build sorted unique solution list (for filter dropdown)
  const allSolutions = useMemo(() => {
    const set = new Set();
    data.forEach((d) => d.solutions.forEach((s) => set.add(s.name)));
    return Array.from(set).sort();
  }, [data]);

  // Filtered data: when a solution is picked, only keep countries having it,
  // and only its solution rows (so totals reflect that single solution).
  const filteredData = useMemo(() => {
    if (solutionFilter === "all") return data;
    return data
      .map((d) => {
        const sols = d.solutions.filter((s) => s.name === solutionFilter);
        if (sols.length === 0) return null;
        const total = sols.reduce((sum, s) => sum + (s.installations || 0), 0);
        return { ...d, solutions: sols, total_installations: total };
      })
      .filter(Boolean);
  }, [data, solutionFilter]);

  const points = useMemo(() => {
    return filteredData
      .map((d) => ({ ...d, coords: findCoords(d.country) }))
      .filter((d) => Array.isArray(d.coords));
  }, [filteredData]);

  const totalCountries = filteredData.length;
  const totalInstalls = filteredData.reduce((s, d) => s + (d.total_installations || 0), 0);
  const totalSolutions = useMemo(() => {
    const set = new Set();
    filteredData.forEach((d) => d.solutions.forEach((s) => set.add(s.name)));
    return set.size;
  }, [filteredData]);

  const radius = (n) => Math.min(18, 4 + Math.sqrt(Math.max(1, n)) * 1.6);

  // Auto-zoom : compute bounding box of all marker coordinates and pick a sensible scale + center.
  // If no markers, default to world view.
  const projectionConfig = useMemo(() => {
    if (points.length === 0) {
      return { rotate: [-10, 0, 0], scale: 145 };
    }
    const lngs = points.map((p) => p.coords[0]);
    const lats = points.map((p) => p.coords[1]);
    let minLng = Math.min(...lngs);
    let maxLng = Math.max(...lngs);
    let minLat = Math.min(...lats);
    let maxLat = Math.max(...lats);
    // Add padding around the bbox so markers aren't clipped at the edges
    const padLng = Math.max(8, (maxLng - minLng) * 0.2);
    const padLat = Math.max(6, (maxLat - minLat) * 0.2);
    minLng -= padLng; maxLng += padLng;
    minLat -= padLat; maxLat += padLat;
    const centerLng = (minLng + maxLng) / 2;
    const centerLat = (minLat + maxLat) / 2;
    const lngSpan = Math.max(8, maxLng - minLng);
    const latSpan = Math.max(6, maxLat - minLat);
    // ComposableMap default 800x600. Empirically, for geoEqualEarth scale ≈ 800 / lngSpan * 1.1 (cap at 600 to avoid over-zoom on a single country).
    const scale = Math.min(600, Math.max(120, Math.min(
      (800 / lngSpan) * 55,
      (600 / latSpan) * 55,
    )));
    return {
      rotate: [-centerLng, 0, 0],
      center: [0, centerLat],
      scale,
    };
  }, [points]);

  return (
    <section className="relative bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 text-white py-20 sm:py-24" data-testid="deployments-section">
      <div className="absolute inset-0 opacity-[0.07] pointer-events-none"
           style={{ backgroundImage: "radial-gradient(circle at 30% 30%, #1E90FF 0%, transparent 60%)" }} />
      <div className="relative max-w-7xl mx-auto px-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-[0.3em] text-sawali-blue mb-3">
          <Globe2 className="h-4 w-4" /> Déploiements à travers le monde
        </div>
        <div className="flex items-end justify-between flex-wrap gap-6 mb-6">
          <h2 className="text-4xl sm:text-5xl font-display font-bold tracking-tight max-w-2xl">
            Nos solutions, déjà <span className="text-sawali-blue">déployées sur 3 continents</span>.
          </h2>
          <div className="flex gap-6 text-sm">
            <div><p className="text-3xl font-display font-bold">{totalInstalls}</p><p className="text-slate-400 text-xs uppercase tracking-widest">Installations</p></div>
            <div><p className="text-3xl font-display font-bold">{totalCountries}</p><p className="text-slate-400 text-xs uppercase tracking-widest">Pays</p></div>
            <div><p className="text-3xl font-display font-bold">{totalSolutions}</p><p className="text-slate-400 text-xs uppercase tracking-widest">Solutions</p></div>
          </div>
        </div>

        {allSolutions.length > 1 && (
          <div className="flex items-center gap-2 mb-4 flex-wrap" data-testid="deployment-solution-filter">
            <span className="text-xs uppercase tracking-widest text-slate-500">Filtrer par solution :</span>
            <button
              type="button"
              onClick={() => setSolutionFilter("all")}
              className={`text-xs px-3 py-1 rounded-full border transition ${solutionFilter === "all" ? "bg-sawali-blue text-white border-sawali-blue" : "bg-transparent text-slate-300 border-white/15 hover:border-sawali-blue/60"}`}
              data-testid="filter-all"
            >
              Toutes ({data.reduce((sum, d) => sum + d.total_installations, 0)})
            </button>
            {allSolutions.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSolutionFilter(s)}
                className={`text-xs px-3 py-1 rounded-full border transition ${solutionFilter === s ? "bg-sawali-blue text-white border-sawali-blue" : "bg-transparent text-slate-300 border-white/15 hover:border-sawali-blue/60"}`}
                data-testid={`filter-${s}`}
              >
                {s}
              </button>
            ))}
          </div>
        )}

        <div className="relative rounded-2xl border border-white/10 bg-slate-900/40 backdrop-blur p-2 sm:p-4" data-testid="deployments-map-container">
          <ComposableMap
            projectionConfig={projectionConfig}
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
                onClick={() => { setHovered(null); setSelected(p); }}
              >
                <circle r={radius(p.total_installations)} fill="#1E90FF" fillOpacity={0.4} stroke="#1E90FF" strokeWidth={1.2} className="cursor-pointer transition-all hover:fill-opacity-70" data-testid={`deployment-marker-${p.country}`} />
                <circle r={3} fill="#fff" className="cursor-pointer pointer-events-none" />
              </Marker>
            ))}
          </ComposableMap>

          {/* List of countries below the map (clickable) */}
          {points.length > 0 && (
            <div className="mt-4 px-2 pb-2 grid sm:grid-cols-2 lg:grid-cols-3 gap-2 text-sm">
              {points.map((p) => (
                <button
                  key={p.country}
                  type="button"
                  onClick={() => setSelected(p)}
                  className="flex items-center justify-between rounded-md border border-white/10 bg-slate-900/60 px-3 py-2 text-left hover:border-sawali-blue/60 hover:bg-slate-800/80 transition"
                  data-testid={`deployment-tile-${p.country}`}
                >
                  <span className="inline-flex items-center gap-2 text-slate-200"><MapPin className="h-3.5 w-3.5 text-sawali-blue" />{p.country}</span>
                  <span className="text-xs text-slate-400 truncate ml-2">
                    {p.solutions.map((s) => `${s.name}: ${s.installations}`).join(" · ")}
                  </span>
                </button>
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
        {hovered && !selected && (
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
            <p className="mt-1.5 text-[10px] text-slate-500 italic">Cliquez pour voir les détails…</p>
          </div>
        )}
      </div>

      {selected && <DetailModal country={selected} onClose={() => setSelected(null)} />}
    </section>
  );
}

// ====================================================================
// Country detail modal (clickable from marker or tile)
// ====================================================================
function DetailModal({ country, onClose }) {
  // Cumulative timeline: sort solutions by created_at, build [{date, cumulative}] points.
  const timeline = useMemo(() => {
    const sols = (country.solutions || [])
      .filter((s) => s.created_at)
      .map((s) => ({ ...s, ts: new Date(s.created_at).getTime() }))
      .sort((a, b) => a.ts - b.ts);
    if (sols.length === 0) return [];
    let cum = 0;
    return sols.map((s) => {
      cum += s.installations;
      return {
        date: new Date(s.ts).toLocaleDateString("fr-FR", { month: "short", year: "numeric" }),
        rawDate: s.ts,
        installations: cum,
        added: s.installations,
        solution: s.name,
      };
    });
  }, [country]);

  const totalCities = useMemo(() => {
    return new Set((country.solutions || []).map((s) => s.city).filter(Boolean)).size;
  }, [country]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-slate-900 border border-sawali-blue/30 rounded-2xl w-full max-w-3xl max-h-[90vh] overflow-auto text-white shadow-2xl"
           onClick={(e) => e.stopPropagation()}
           data-testid="deployment-detail-modal">
        <div className="flex items-center justify-between p-5 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center justify-center h-10 w-10 rounded-full bg-sawali-blue/15 border border-sawali-blue/40">
              <MapPin className="h-5 w-5 text-sawali-blue" />
            </span>
            <div>
              <h3 className="text-xl font-display font-bold text-white">{country.country}</h3>
              <p className="text-xs text-slate-400">
                {country.total_installations} installation{country.total_installations > 1 ? "s" : ""}
                {totalCities > 0 && ` · ${totalCities} ville${totalCities > 1 ? "s" : ""}`}
                {" · "}{country.solutions?.length || 0} solution{(country.solutions?.length || 0) > 1 ? "s" : ""}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white" data-testid="close-detail-modal">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-5 space-y-6">
          {/* Solutions list */}
          <div>
            <h4 className="text-xs uppercase tracking-[0.2em] text-slate-500 mb-3">Solutions installées</h4>
            <div className="space-y-2">
              {(country.solutions || []).map((s) => (
                <div key={s.name + (s.city || "")} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/40 px-4 py-3">
                  <div>
                    <p className="font-display font-semibold text-sm text-white">{s.name}</p>
                    <p className="text-xs text-slate-400">
                      {s.city ? <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{s.city}</span> : <span className="text-slate-500">Localisation non précisée</span>}
                      {s.created_at && (
                        <span className="ml-3 inline-flex items-center gap-1">
                          <Calendar className="h-3 w-3" />
                          {new Date(s.created_at).toLocaleDateString("fr-FR")}
                        </span>
                      )}
                    </p>
                  </div>
                  <span className="text-2xl font-display font-bold text-sawali-blue">{s.installations}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Cumulative installations chart */}
          {timeline.length >= 1 ? (
            <div>
              <h4 className="text-xs uppercase tracking-[0.2em] text-slate-500 mb-1">Évolution cumulative des installations</h4>
              <p className="text-xs text-slate-400 mb-3">
                {timeline.length === 1 ? "Une seule date d'installation enregistrée." : `${timeline.length} jalons sur ${Math.round((timeline[timeline.length - 1].rawDate - timeline[0].rawDate) / (1000 * 60 * 60 * 24))} jours.`}
              </p>
              <div className="h-56 -mx-2" data-testid="deployment-detail-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={timeline} margin={{ top: 10, right: 16, bottom: 0, left: -20 }}>
                    <defs>
                      <linearGradient id="depGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#1E90FF" stopOpacity={0.6} />
                        <stop offset="100%" stopColor="#1E90FF" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                    <XAxis dataKey="date" stroke="#64748b" tick={{ fontSize: 11 }} />
                    <YAxis stroke="#64748b" tick={{ fontSize: 11 }} allowDecimals={false} />
                    <RechartsTooltip
                      contentStyle={{ background: "#0f172a", border: "1px solid #1E90FF", borderRadius: 8, color: "#fff", fontSize: 12 }}
                      labelStyle={{ color: "#94a3b8" }}
                      formatter={(value, name, props) => {
                        if (name === "installations") return [value, "Total cumulé"];
                        return [value, name];
                      }}
                    />
                    <Area type="monotone" dataKey="installations" stroke="#1E90FF" strokeWidth={2} fill="url(#depGrad)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : (
            <p className="text-xs text-slate-500 italic">Aucune date d'installation enregistrée.</p>
          )}
        </div>
      </div>
    </div>
  );
}
