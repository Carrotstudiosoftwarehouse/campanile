// DEVELOPED BY CARROTSTUDIO software house
// The map's look, shared by the map page and the setup page. Libraries, fonts, icons
// and data all come from the Campanile: no internet.
import * as maplibregl from "/vendor/maplibre-gl.mjs";
import { lang } from "/i18n.js";

/* global pmtiles, basemaps */

const ORIGIN = location.origin;
const THEME = "light";

export { maplibregl };

function mapUrl(file) {
  return `${ORIGIN}/maps/${encodeURIComponent(file)}`;
}

export function registerPmtiles() {
  maplibregl.addProtocol("pmtiles", new pmtiles.Protocol().tile);
}

export async function readHeader(file) {
  const header = await new pmtiles.PMTiles(mapUrl(file)).getHeader();
  return {
    bounds: [[header.minLon, header.minLat], [header.maxLon, header.maxLat]],
    maxZoom: header.maxZoom,
  };
}

export function style(file) {
  return {
    version: 8,
    glyphs: `${ORIGIN}/vendor/fonts/{fontstack}/{range}.pbf`,
    sprite: `${ORIGIN}/vendor/sprites/v4/${THEME}`,
    sources: {
      protomaps: {
        type: "vector",
        url: `pmtiles://${mapUrl(file)}`,
        // In a tab of its own: a finger landing on it must never take the map away (offline,
        // the page it opens doesn't even load).
        attribution:
          '<a href="https://openstreetmap.org/copyright" target="_blank" rel="noopener">' +
          "© OpenStreetMap</a> · ESA WorldCover (CC BY 4.0) · Protomaps",
      },
    },
    layers: basemaps.layers("protomaps", basemaps.namedFlavor(THEME), { lang }),
  };
}
