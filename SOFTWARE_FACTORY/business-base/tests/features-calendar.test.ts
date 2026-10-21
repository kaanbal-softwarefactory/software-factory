import { test } from "node:test";
import assert from "node:assert/strict";
import { enabledModules } from "../lib/features";
import { calendarDay, calendarWindow, monday, shiftDay } from "../lib/calendar";

test("legacy presets retain defaults while an explicit empty selection means core only", () => {
  assert.deepEqual(enabledModules("starter"), ["contact"]);
  assert.deepEqual(enabledModules("services"), ["contact", "catalog", "appointments"]);
  assert.deepEqual(enabledModules("barber", []), []);
  assert.deepEqual(enabledModules("starter", ["appointments"]), ["catalog", "appointments"]);
});
test("calendar groups by the business day across UTC and DST boundaries", () => {
  assert.equal(calendarDay(new Date("2026-11-01T05:30:00Z"), "America/New_York"), "2026-11-01");
  assert.equal(calendarDay(new Date("2026-11-01T06:30:00Z"), "America/New_York"), "2026-11-01");
  assert.equal(calendarDay(new Date("2026-01-01T01:00:00Z"), "America/Los_Angeles"), "2025-12-31");
  assert.equal(monday("2026-11-01"), "2026-10-26");
  assert.equal(shiftDay("2026-12-31", 1), "2027-01-01");
  const window = calendarWindow("2026-10-26");
  assert.ok(Date.parse(window.from) <= Date.parse("2026-10-26T00:00:00+14:00"));
  assert.ok(Date.parse(window.to) >= Date.parse("2026-11-02T00:00:00-12:00"));
});
