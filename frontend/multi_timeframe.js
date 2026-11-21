(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.AITraderMultiTimeframe = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function resolveConsensus(data) {
    const frames = data && data.timeframes;
    if (!frames || typeof frames !== "object") return "NEUTRAL";
    const oneHour = frames["1h"];
    const fourHour = frames["4h"];
    if (oneHour?.available !== true || fourHour?.available !== true) return "NEUTRAL";

    const signal1h = String(oneHour.signal || "NEUTRAL").toUpperCase();
    const signal4h = String(fourHour.signal || "NEUTRAL").toUpperCase();
    const apiConsensus = String(data.consensus || "NEUTRAL").toUpperCase();
    if (
      !["LONG", "SHORT"].includes(signal1h) ||
      signal1h !== signal4h ||
      apiConsensus !== signal1h
    ) return "NEUTRAL";
    return signal1h;
  }

  function createRequestGate() {
    let inFlight = false;
    return {
      enter() {
        if (inFlight) return false;
        inFlight = true;
        return true;
      },
      leave() {
        inFlight = false;
      }
    };
  }

  return { resolveConsensus, createRequestGate };
});
