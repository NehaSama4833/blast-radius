# Deploying Blast Radius (Saturday checklist)

1. **FalkorDB Cloud**: create a free instance, copy the `redis://...` or `rediss://...` connection string.
2. **Render** (API): New > Blueprint > pick this repo (uses `render.yaml`). Set `FALKORDB_URL`, `ALLOWED_ORIGINS` (the Vercel URL, set after step 3), optional `ANTHROPIC_API_KEY` and `DISCORD_WEBHOOK_URL`. Check `/api/health`.
3. **Vercel** (UI): import the repo, root directory `frontend`. Edit `frontend/vercel.json`: already points at blast-radius-sg.onrender.com; change it if your Render URL differs. The UI calls `/api/...`, Vercel forwards it to Render.
4. Come back to Render and set `ALLOWED_ORIGINS` to the Vercel URL.
5. Smoke test: open the Vercel URL, press Surprise me, then Investigate.

Safety limits already in the code: 30 requests/min per visitor, 200 investigations/day (then a recorded replay is shown), the server posts only its own drafted Discord message, sandboxes are deleted after 2 hours (swept every 10 minutes).
Local full stack: `docker compose up --build` then `cd frontend && npm run dev`.
