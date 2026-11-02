import React from "react";
import type { Props } from "./types";
import { Button } from "@/components/Button";
import { fmt } from "@shared/util";
import { a, b } from "./lib";

export async function boot() {
  const lazy = await import("@/lazy");
  const legacy = require("./legacy.cjs");
  return [React, Button, fmt, a, b, lazy, legacy];
}
export const App = (p: Props) => <Button {...p} />;
