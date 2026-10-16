import { createClient, type User } from "@supabase/supabase-js";
import { ENV } from "./env";

function getPublicClient() {
  if (!ENV.supabaseUrl || !ENV.supabaseAnonKey) return null;
  return createClient(ENV.supabaseUrl, ENV.supabaseAnonKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

function getAdminClient() {
  if (!ENV.supabaseUrl || !ENV.supabaseServiceRoleKey) return null;
  return createClient(ENV.supabaseUrl, ENV.supabaseServiceRoleKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

export async function getSupabaseUserFromRequest(req: { headers: { authorization?: string } }): Promise<User | null> {
  const authorization = req.headers.authorization ?? "";
  const token = authorization.startsWith("Bearer ") ? authorization.slice("Bearer ".length).trim() : "";
  const client = getPublicClient();
  if (!token || !client) return null;

  const { data, error } = await client.auth.getUser(token);
  return error ? null : data.user;
}

export async function inviteSupabaseMember(email: string) {
  const client = getAdminClient();
  if (!client) {
    throw new Error("Supabase invite service is not configured. Add the service-role key in project secrets.");
  }

  const { data, error } = await client.auth.admin.inviteUserByEmail(email, {
    data: { tmpserver_invited: true },
  });
  if (error || !data.user) throw new Error(error?.message ?? "Supabase could not create the invite.");

  const appMetadata = { ...(data.user.app_metadata ?? {}), tmpserver_access: true };
  const { error: metadataError } = await client.auth.admin.updateUserById(data.user.id, {
    app_metadata: appMetadata,
  });
  if (metadataError) throw new Error(metadataError.message);

  return { id: data.user.id, email: data.user.email ?? email };
}

export function isSupabaseOwner(user: User) {
  return Boolean(user.email && ENV.supabaseOwnerEmail && user.email.toLowerCase() === ENV.supabaseOwnerEmail.toLowerCase());
}
