import { describe, expect, it } from "vitest";

import { EngineClient } from "./engineClient";

function client() {
  const sent: any[] = [];
  const c = new EngineClient((line) => sent.push(JSON.parse(line)));
  return { c, sent };
}

describe("EngineClient", () => {
  it("sends requests and resolves results by id", async () => {
    const { c, sent } = client();
    const { id, result } = c.call("version", {});
    expect(sent[0]).toEqual({ id, method: "version", params: {} });
    c.handleLine(JSON.stringify({ id, result: { engine: "0.1.0" } }));
    await expect(result).resolves.toEqual({ engine: "0.1.0" });
  });

  it("routes events to the job that produced them", () => {
    const { c } = client();
    const seen: string[] = [];
    const a = c.call("recover", {}, (m) => seen.push(`a:${m.event}`));
    c.call("image", {}, (m) => seen.push(`b:${m.event}`));
    c.handleLine(JSON.stringify({ event: "progress", job: a.id, data: {} }));
    c.handleLine(JSON.stringify({ event: "phase", job: a.id + 1, data: {} }));
    expect(seen).toEqual(["a:progress", "b:phase"]);
  });

  it("rejects with the engine's error detail", async () => {
    const { c } = client();
    const { id, result } = c.call("analyze", { source: "x" });
    c.handleLine(JSON.stringify({ id, error: { type: "SourceUnavailable", message: "x: not found" } }));
    await expect(result).rejects.toEqual({ type: "SourceUnavailable", message: "x: not found" });
  });

  it("uses caller-chosen ids, signals ready, ignores junk, fails pending on exit", async () => {
    const { c, sent } = client();
    const { result } = c.call("version", {}, undefined, 42);
    expect(sent[0].id).toBe(42);
    c.handleLine("not json");
    c.handleLine(JSON.stringify({ event: "ready", data: { protocol: 1 } }));
    await c.ready;
    c.failAll("gone");
    await expect(result).rejects.toMatchObject({ type: "EngineStopped" });
  });

  it("sends cancel requests", () => {
    const { c, sent } = client();
    c.cancel(5);
    expect(sent[0]).toMatchObject({ method: "cancel", params: { job: 5 } });
  });
});
