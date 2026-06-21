// Keycloak (OIDC, Authorization Code + PKCE) integration for the SPA.
"use client";
import Keycloak from "keycloak-js";

let kc: Keycloak | null = null;

export function getKeycloak(): Keycloak {
  if (!kc) {
    kc = new Keycloak({
      url: process.env.NEXT_PUBLIC_KEYCLOAK_URL!,
      realm: process.env.NEXT_PUBLIC_KEYCLOAK_REALM!,
      clientId: process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID!,
    });
  }
  return kc;
}

export async function initAuth(): Promise<boolean> {
  const k = getKeycloak();
  return k.init({ onLoad: "login-required", pkceMethod: "S256", checkLoginIframe: false });
}

export async function getToken(): Promise<string | null> {
  const k = getKeycloak();
  if (!k.authenticated) return null;
  await k.updateToken(30).catch(() => k.login());
  return k.token ?? null;
}

export function hasRole(role: string): boolean {
  return getKeycloak().hasRealmRole(role);
}
