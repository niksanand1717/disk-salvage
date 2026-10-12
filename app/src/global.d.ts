import type { SalvageBridge } from "./shared/protocol";

declare global {
  interface Window {
    salvage: SalvageBridge;
  }
}

export {};
