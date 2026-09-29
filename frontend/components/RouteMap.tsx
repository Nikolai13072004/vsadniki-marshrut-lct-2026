"use client";
import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import { colors, Dataset, hm, Plan, Stop } from "@/lib/types";

export default function RouteMap({
  dataset,
  plan,
  comparePlan,
  engineerId,
  onSelect,
}: {
  dataset: Dataset;
  plan: Plan | null;
  comparePlan?: Plan | null;
  engineerId: string;
  onSelect: (id: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const routeLayerRef = useRef<L.LayerGroup | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    if (!container.current) return;
    const map = L.map(container.current, {
      zoomControl: false,
      scrollWheelZoom: true,
    }).setView([55.69, 37.68], 11);
    map.attributionControl.setPrefix(
      '<a href="https://leafletjs.com">Leaflet</a>',
    );
    L.control.zoom({ position: "bottomright" }).addTo(map);
    const tiles = L.tileLayer(
      process.env.NEXT_PUBLIC_TILE_URL ||
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        maxZoom: 19,
        attribution:
          '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      },
    ).addTo(map);
    tiles.on("tileerror", () => setOffline(true));
    mapRef.current = map;
    routeLayerRef.current = L.layerGroup().addTo(map);
    const resize = new ResizeObserver(() => map.invalidateSize(false));
    resize.observe(container.current);
    return () => {
      resize.disconnect();
      map.stop();
      map.off();
      map.remove();
      mapRef.current = null;
      routeLayerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layer = routeLayerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();
    const points: L.LatLngTuple[] = [];
    dataset.engineers.forEach((engineer) => {
      if (
        !engineer.start_location ||
        (engineerId && engineer.id !== engineerId)
      )
        return;
      const p = engineer.start_location;
      if (
        dataset.office_location &&
        p.latitude === dataset.office_location.latitude &&
        p.longitude === dataset.office_location.longitude
      )
        return;
      points.push([p.latitude, p.longitude]);
      const label = document.createElement("span");
      label.textContent = `Старт: ${engineer.name}`;
      L.marker([p.latitude, p.longitude], {
        title: `Старт: ${engineer.name}`,
        icon: L.divIcon({
          className: "office-pin",
          html: "<span>С</span>",
          iconSize: [30, 30],
          iconAnchor: [15, 15],
        }),
      })
        .addTo(layer)
        .bindTooltip(label);
    });
    const previousAssignments = new Map<string, string>();
    comparePlan?.routes.forEach((route) => {
      route.stops.forEach((stop, order) => {
        previousAssignments.set(
          stop.job_id,
          `${route.engineer_id}:${order}:${stop.start}`,
        );
      });
      if (engineerId && route.engineer_id !== engineerId) return;
      route.legs.forEach((leg) => {
        L.polyline(
          [
            [leg.from.latitude, leg.from.longitude],
            [leg.to.latitude, leg.to.longitude],
          ],
          { color: "#596459", weight: 3, opacity: 0.55, dashArray: "3 8" },
        ).addTo(layer);
      });
    });
    const assignments = new Map<
      string,
      { index: number; order: number; stop: Stop; engineerId: string }
    >();
    plan?.routes.forEach((route, index) => {
      route.stops.forEach((stop, order) =>
        assignments.set(stop.job_id, {
          index,
          order: order + 1,
          stop,
          engineerId: route.engineer_id,
        }),
      );
      if (engineerId && route.engineer_id !== engineerId) return;
      route.legs.forEach((leg) => {
        L.polyline(
          [
            [leg.from.latitude, leg.from.longitude],
            [leg.to.latitude, leg.to.longitude],
          ],
          {
            color: colors[index % colors.length],
            weight: 3,
            opacity: 0.8,
            dashArray: "7 5",
          },
        ).addTo(layer);
      });
    });
    dataset.jobs.forEach((job) => {
      if (!job.location) return;
      const assigned = assignments.get(job.id);
      if (
        engineerId &&
        (!assigned || plan?.routes[assigned.index].engineer_id !== engineerId)
      )
        return;
      const point: L.LatLngTuple = [
        job.location.latitude,
        job.location.longitude,
      ];
      points.push(point);
      const label = document.createElement("span");
      label.textContent = assigned
        ? `${assigned.order}. ${job.source_id || job.id} · ${hm(assigned.stop.start)} · ${job.address}`
        : `${job.source_id || job.id}: ${job.address}`;
      const changed =
        !!comparePlan &&
        previousAssignments.get(job.id) !==
          (assigned
            ? `${assigned.engineerId}:${assigned.order - 1}:${assigned.stop.start}`
            : undefined);
      const marker = assigned
        ? L.marker(point, {
            icon: L.divIcon({
              className: `route-stop-pin${changed ? " changed" : ""}`,
              html: `<span style="background:${colors[assigned.index % colors.length]}">${assigned.order}</span>`,
              iconSize: [26, 26],
              iconAnchor: [13, 13],
            }),
          }).addTo(layer)
        : L.circleMarker(point, {
            radius: 6,
            color: changed ? "#b34937" : "#fff",
            weight: changed ? 3 : 2,
            fillColor: plan ? "#c85543" : "#718176",
            fillOpacity: 1,
          }).addTo(layer);
      marker.bindTooltip(label).on("click", () => onSelect(job.id));
    });
    if (dataset.office_location) {
      const p: L.LatLngTuple = [
        dataset.office_location.latitude,
        dataset.office_location.longitude,
      ];
      points.push(p);
      L.marker(p, {
        icon: L.divIcon({
          className: "office-pin",
          html: "<span>О</span>",
          iconSize: [30, 30],
          iconAnchor: [15, 15],
        }),
        title: "Офис - стартовая точка",
      })
        .addTo(layer)
        .bindTooltip("Офис - стартовая точка");
    }
    if (points.length)
      map.fitBounds(L.latLngBounds(points), {
        padding: [35, 35],
        maxZoom: 14,
        animate: false,
      });
  }, [dataset, plan, comparePlan, engineerId, onSelect]);
  return (
    <div className="map-shell">
      <div
        ref={container}
        className="map"
        aria-label="Карта заявок и маршрутов"
      />
      <div className="map-label">
        <span className="office-key" /> Офис <span className="dot-key" /> Заявки{" "}
        <span className="line-key" /> Маршрут
        {comparePlan ? (
          <>
            <span className="old-line-key" /> До{" "}
            <span className="changed-key" /> Изменено
          </>
        ) : null}
      </div>
      {offline ? (
        <div className="map-offline" role="status">
          Подложка карты недоступна. Точки, маршруты и расписание сохранены.
        </div>
      ) : null}
    </div>
  );
}
