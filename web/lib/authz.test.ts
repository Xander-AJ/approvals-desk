import { describe, expect, it } from "vitest";
import { findMembership, isAllowed, membershipsFor, parseAllowlist } from "./authz";

const T1 = "11111111-1111-1111-1111-111111111111";
const T2 = "22222222-2222-2222-2222-222222222222";
const RAW = JSON.stringify({
  "12345": [
    { tenantId: T1, tenantName: "Mzigo Wallet", role: "admin" },
    { tenantId: T2, tenantName: "Duka", role: "reviewer" },
  ],
});

describe("parseAllowlist", () => {
  it("denies everyone when unset or empty", () => {
    expect(parseAllowlist(undefined).size).toBe(0);
    expect(parseAllowlist("").size).toBe(0);
    expect(parseAllowlist("{}").size).toBe(0);
  });

  it("parses memberships and normalises tenant ids", () => {
    const list = parseAllowlist(JSON.stringify({ "1": [{ tenantId: T1.toUpperCase(), tenantName: "x", role: "agent" }] }));
    expect(membershipsFor(list, "1")[0].tenantId).toBe(T1);
  });

  it.each([
    ["a login name instead of an id", { Xander_AJ: [] }],
    ["a non-array value", { "1": { tenantId: T1 } }],
    ["a bad tenant id", { "1": [{ tenantId: "nope", tenantName: "x", role: "admin" }] }],
    ["an unknown role", { "1": [{ tenantId: T1, tenantName: "x", role: "superuser" }] }],
    ["a missing tenant name", { "1": [{ tenantId: T1, role: "admin" }] }],
  ])("fails loudly on %s", (_label, data) => {
    expect(() => parseAllowlist(JSON.stringify(data))).toThrow();
  });

  it("fails loudly on invalid JSON or a non-object", () => {
    expect(() => parseAllowlist("{oops")).toThrow();
    expect(() => parseAllowlist("[]")).toThrow(/object/);
  });
});

describe("authorization decisions", () => {
  const list = parseAllowlist(RAW);

  it("allows only listed users, by immutable id", () => {
    expect(isAllowed(list, "12345")).toBe(true);
    expect(isAllowed(list, "99999")).toBe(false);
    expect(isAllowed(list, undefined)).toBe(false);
    expect(isAllowed(list, "")).toBe(false);
    expect(isAllowed(list, "xander-aj")).toBe(false); // a login name never matches
  });

  it("grants exactly the listed (tenant, role) pairs", () => {
    expect(findMembership(list, "12345", T1, "admin")?.tenantName).toBe("Mzigo Wallet");
    expect(findMembership(list, "12345", T2, "reviewer")).not.toBeNull();
  });

  it("refuses escalation: same tenant with a role that was not granted", () => {
    expect(findMembership(list, "12345", T2, "admin")).toBeNull();
    expect(findMembership(list, "12345", T1, "agent")).toBeNull();
  });

  it("refuses a tenant that was not granted, and unknown users", () => {
    expect(findMembership(list, "12345", "33333333-3333-3333-3333-333333333333", "admin")).toBeNull();
    expect(findMembership(list, "99999", T1, "admin")).toBeNull();
  });
});
