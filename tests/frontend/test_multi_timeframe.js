const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {
  resolveConsensus,
  createRequestGate
} = require("../../frontend/multi_timeframe.js");

function payload(signal1h, signal4h, consensus, available1h = true, available4h = true) {
  return {
    consensus,
    timeframes: {
      "1h": { available: available1h, signal: signal1h },
      "4h": { available: available4h, signal: signal4h }
    }
  };
}

test("matching available 1h and 4h signals preserve directional consensus", () => {
  assert.equal(resolveConsensus(payload("LONG", "LONG", "LONG")), "LONG");
  assert.equal(resolveConsensus(payload("SHORT", "SHORT", "SHORT")), "SHORT");
});

test("incomplete timeframe data always resolves to NEUTRAL", () => {
  assert.equal(resolveConsensus(payload("LONG", "LONG", "LONG", true, false)), "NEUTRAL");
  assert.equal(resolveConsensus({ consensus: "LONG", timeframes: { "1h": { available: true, signal: "LONG" } } }), "NEUTRAL");
});

test("contradictory timeframe directions always resolve to NEUTRAL", () => {
  assert.equal(resolveConsensus(payload("LONG", "SHORT", "NEUTRAL")), "NEUTRAL");
});

test("API consensus inconsistent with timeframe signals resolves to NEUTRAL", () => {
  assert.equal(resolveConsensus(payload("LONG", "LONG", "SHORT")), "NEUTRAL");
});

test("request gate prevents overlapping periodic/manual requests", () => {
  const gate = createRequestGate();
  assert.equal(gate.enter(), true);
  assert.equal(gate.enter(), false);
  gate.leave();
  assert.equal(gate.enter(), true);
  gate.leave();
});

test("dashboard renders the NO_GO warning and avoids innerHTML sinks", () => {
  const dashboard = fs.readFileSync(path.join(__dirname, "../../frontend/index.html"), "utf8");
  const warning = "Estrategia NO_GO — niveles ilustrativos, sin ventaja demostrada; la regla 1h/4h no está validada";
  assert.ok(dashboard.includes(warning));
  assert.doesNotMatch(dashboard, /\.innerHTML\b/);
  assert.match(dashboard, /multiTimeframeRequestGate\.enter\(\)/);
  assert.match(dashboard, /multiTimeframeRequestGate\.leave\(\)/);
});
