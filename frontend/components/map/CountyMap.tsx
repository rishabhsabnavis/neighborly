"use client";

import type { GeoJsonObject } from "geojson";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { Fragment, useEffect } from "react";
import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";

import { RiskChip } from "@/components/raw/RiskChip";
import { pinColor } from "@/lib/display";
import type { PolicyholderRow } from "@/lib/types";
import counties from "@/lib/fl-counties.json";

const shapes = counties as unknown as GeoJsonObject;

function FitCounties() {
  const map = useMap();
  useEffect(() => {
    const layer = L.geoJSON(shapes);
    const bounds = layer.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [28, 28] });
  }, [map]);
  return null;
}

export default function CountyMap({
  rows,
  selectedId,
  onSelect,
}: {
  rows: PolicyholderRow[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="relative h-full w-full">
      <MapContainer
        center={[30.45, -85.6]}
        zoom={8}
        zoomControl={false}
        className="h-full w-full"
        attributionControl
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          className="map-muted"
        />
        <GeoJSON
          data={shapes}
          style={{
            color: "#98A2B3",
            weight: 1.5,
            dashArray: "6 4",
            fillColor: "#D0D5DD",
            fillOpacity: 0.55,
          }}
        />
        <FitCounties />
        <Pins rows={rows} selectedId={selectedId} onSelect={onSelect} />
      </MapContainer>
      <p className="pointer-events-none absolute top-4 left-5 text-[11px] font-semibold tracking-[0.16em] text-zinc-500">
        AFFECTED ZONE
      </p>
      <div className="absolute bottom-4 left-4 rounded-md border border-zinc-200 bg-white px-3 py-2 shadow-sm">
        <p className="text-[12px] font-medium text-zinc-700">Risk level</p>
        <ul className="mt-1 space-y-1 text-[13px] text-zinc-700">
          <Legend color="#D92D20" label="Critical" />
          <Legend color="#F79009" label="High" />
          <Legend color="#EAB308" label="Moderate" />
          <Legend color="#12B76A" label="Safe" />
        </ul>
      </div>
    </div>
  );
}

function Pins({
  rows,
  selectedId,
  onSelect,
}: {
  rows: PolicyholderRow[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <>
      {rows.map((row) => {
        const selected = row.id === selectedId;
        const color = pinColor(row.urgency);
        return (
          <Fragment key={row.id}>
            {row.live ? (
              <CircleMarker
                center={[row.lat, row.lng]}
                radius={selected ? 16 : 13}
                pathOptions={{ color: "#FFFFFF", weight: 3, fillOpacity: 0 }}
              />
            ) : null}
            {row.human_requested ? (
              <CircleMarker
                center={[row.lat, row.lng]}
                radius={selected ? 14 : 11}
                pathOptions={{ color: "#7A5AF8", weight: 2, fillOpacity: 0 }}
              />
            ) : null}
            <CircleMarker
              center={[row.lat, row.lng]}
              radius={selected ? 9 : 7}
              pathOptions={{
                color: "#FFFFFF",
                weight: 2,
                fillColor: color,
                fillOpacity: 1,
                className: row.status === "calling" ? "pin-calling" : undefined,
              }}
            >
              <Popup>
                <div className="min-w-[200px] font-sans text-[14px] text-zinc-900">
                  <div className="flex items-center justify-between gap-2">
                    <strong>{row.name}</strong>
                    <RiskChip row={row} />
                  </div>
                  <p className="mt-1 text-zinc-600">{row.summary || "No details yet"}</p>
                  <button
                    type="button"
                    className="mt-2 text-sm font-medium text-zinc-900 underline"
                    onClick={() => onSelect(row.id)}
                  >
                    Open details →
                  </button>
                </div>
              </Popup>
            </CircleMarker>
          </Fragment>
        );
      })}
    </>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <li className="flex items-center gap-2">
      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </li>
  );
}
