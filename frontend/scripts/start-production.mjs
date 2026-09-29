import { cp, access } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import { resolve } from "node:path";

// Next standalone output needs static assets copied alongside server.js.
const root = fileURLToPath(new URL("../", import.meta.url));
const standalone = resolve(root, ".next/standalone");
await access(resolve(standalone, "server.js"));
await cp(resolve(root, ".next/static"), resolve(standalone, ".next/static"), {
  recursive: true,
});
await cp(resolve(root, "public"), resolve(standalone, "public"), {
  recursive: true,
}).catch((error) => {
  if (error.code !== "ENOENT") throw error;
});
process.env.HOSTNAME ||= "127.0.0.1";
await import(pathToFileURL(resolve(standalone, "server.js")).href);
