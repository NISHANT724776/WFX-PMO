# Put WFX PMO online for free (Vercel + Render + Neon)

You need three free accounts and a GitHub account. About 30 to 45 minutes the first time.

| Part | Service | What it hosts |
|---|---|---|
| Frontend | Vercel | the website |
| Backend | Render (free web service) | the API |
| Database | Neon (free PostgreSQL) | all the data |

Free-plan facts to know: the Render backend goes to sleep after about 15 minutes idle and takes up to a minute to wake; its disk is wiped on every restart, so saved copies of uploaded Excel files are lost (imported data lives in the database and survives). Check each service's current free terms before relying on them.

## 0. Put the code on GitHub (private)
The project is not a Git repository yet and must not be published with its data. The `.gitignore` in this folder already keeps `.env`, the local database, uploads and all `.xlsx` / `.pptx` files out.

1. Create an empty **private** repository on GitHub (no README).
2. In the project folder:
```powershell
git init
git add .
git status        # check: no .env, no .xlsx, no dev.db in the list
git commit -m "WFX PMO"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

## 1. Database (Neon)
1. neon.tech, sign up, **Create project** (any name, nearest region).
2. Copy the **connection string** (it starts `postgresql://` and ends `?sslmode=require`). Keep it secret.

## 2. Backend (Render)
1. render.com, sign up with GitHub, **New → Blueprint**, pick the repository. Render reads `render.yaml`.
2. Fill the three secret values when asked:
   - `DATABASE_URL`: the Neon string from step 1
   - `ADMIN_PASSWORD`: a new strong password (10+ characters), not the one you use locally
   - `CORS_ORIGINS`: leave a placeholder for now (`https://placeholder.vercel.app`)
3. Deploy. On start the container creates the tables (Alembic) and the first admin user.
4. Open `https://<your-service>.onrender.com/health`. You should see `{"status":"ok"}`. Copy that address.

## 3. Frontend (Vercel)
1. vercel.com, sign up with GitHub, **Add New → Project**, pick the repository.
2. **Root Directory: `frontend`**.
3. Environment variable: `NEXT_PUBLIC_API_URL` = the Render address (no trailing slash).
4. Deploy. Copy the address Vercel gives you (for example `https://wfx-pmo.vercel.app`).

## 4. Connect them
In Render: **Environment → `CORS_ORIGINS`** = the Vercel address (no trailing slash). Save; Render redeploys.

## 5. First use
1. Open the Vercel address and sign in with `admin@example.com` and the `ADMIN_PASSWORD` you set.
2. **Administration → Users → New user** for your senior (give them their own login).
3. **Smart Import**: upload the Tegra and Shahi workbooks again. Local data does not move to the online database by itself.

## If something fails
- Sign-in shows a network error: the backend is waking up (wait a minute) or `CORS_ORIGINS` does not exactly match the Vercel address.
- Render shows a failed deploy: open its logs. A database error usually means the `DATABASE_URL` was pasted wrongly.
- Changing code: push to GitHub and both services redeploy by themselves.
