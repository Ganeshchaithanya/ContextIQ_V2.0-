# ContextIQ V2 hackathon hosting

Render runs the ContextIQ app, its API, SQLite, and the BrightMart API under
`/shop`. Vercel serves the separate BrightMart website. The BrightMart cart
stays in the store browser until the user selects **Track in ContextIQ** or
**Check out with ContextIQ**.

1. In Vercel, import `Ganeshchaithanya/ContextIQ_V2.0-` and set the root directory to
   `brightmart`. Choose a free Hobby workspace and a project name. Note its
   production domain. Vercel reads the build settings from `brightmart/vercel.json`.
2. In Render, create a Blueprint from the same repository on `main`. Set
   `CONTEXTIQ_STORE_URL` to the Vercel production origin, including `https://`.
   Render generates the signing secret and runs the free web service.
3. Set `RENDER_APP_URL` in the Vercel project's Production environment to the
   HTTPS origin of the Render service. Deploy from `main`. If you change either
   domain, update the corresponding environment variable on the other platform.
4. Verify `/api/config` on Render, then open each site in a private browser
   window. Follow the [judge walkthrough](DEMO.md) through the kirana demo,
   signed cart handoff, and mock checkout. Share the two production URLs.

The hosted demo uses fictional data and mock payments. Render's free service
can take time to wake and its local SQLite data can reset when the instance
restarts. Price checks run when invoked and while the tracking view is open.
