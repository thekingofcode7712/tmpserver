import { createClient, type Session } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;
export const ownerEmail = (import.meta.env.VITE_SUPABASE_OWNER_EMAIL as string | undefined)?.trim().toLowerCase() ?? "";

export const supabaseConfigured = Boolean(url && anonKey && ownerEmail);
export const supabase = supabaseConfigured ? createClient(url!, anonKey!, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
}) : null;

export function isOwnerSession(session: Session | null) {
  return Boolean(session?.user.email && ownerEmail && session.user.email.toLowerCase() === ownerEmail);
}
