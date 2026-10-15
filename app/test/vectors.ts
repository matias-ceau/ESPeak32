import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const DIR = fileURLToPath(new URL("../../protocol/vectors/", import.meta.url));

export function vector(name: string): Uint8Array {
  return new Uint8Array(readFileSync(DIR + name));
}

export function vectorText(name: string): string {
  return readFileSync(DIR + name, "utf8");
}

export function fixture(name: string): Uint8Array {
  return new Uint8Array(readFileSync(fileURLToPath(new URL("./fixtures/" + name, import.meta.url))));
}
