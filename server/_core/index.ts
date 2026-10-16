import "dotenv/config";
import express from "express";
import { createServer } from "http";
import { createExpressMiddleware } from "@trpc/server/adapters/express";
import { registerOAuthRoutes } from "./oauth";
import { publicPlatformScript } from "./publicConfig";
import { getSupabaseUserFromRequest, inviteSupabaseMember, isSupabaseOwner } from "./supabase";
import { appRouter } from "../routers";
import { createContext } from "./context";
import { serveStatic, setupVite } from "./vite";
import { z } from "zod";

async function startServer() {
  const app = express();
  const server = createServer(app);
  // Configure body parser with larger size limit for file uploads
  app.use(express.json({ limit: "50mb" }));
  app.use(express.urlencoded({ limit: "50mb", extended: true }));
  app.get("/api/health", (_req, res) => res.json({ status: "ok" }));
  app.post("/api/owner/invite", async (req, res) => {
    const user = await getSupabaseUserFromRequest(req);
    if (!user || !isSupabaseOwner(user)) {
      res.status(403).json({ error: "Only the configured TMP Server owner can invite members." });
      return;
    }

    const parsed = z.object({ email: z.string().email().max(320) }).safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: "Enter a valid invite email." });
      return;
    }

    try {
      const invited = await inviteSupabaseMember(parsed.data.email.toLowerCase());
      res.json({ ok: true, invited });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Invite failed.";
      res.status(503).json({ error: message });
    }
  });
  app.get("/api/platform/config.js", (_req, res) => {
    res.set("Cache-Control", "no-store").type("application/javascript").send(publicPlatformScript());
  });
  registerOAuthRoutes(app);
  // tRPC API
  app.use(
    "/api/trpc",
    createExpressMiddleware({
      router: appRouter,
      createContext,
    })
  );
  // development mode uses Vite, production mode uses static files
  if (process.env.NODE_ENV === "development") {
    await setupVite(app, server);
  } else {
    serveStatic(app);
  }

  const port = Number(process.env.PORT || "3000");
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid PORT");
  server.on("error", error => { console.error("Server failed:", error.message); process.exit(1); });
  server.listen(port, "0.0.0.0", () => console.log(`Server listening on port ${port}`));
}

startServer().catch(error => { console.error(error); process.exit(1); });
