# ContextIQ V2 hackathon hosting

Render runs the ContextIQ API, SQLite, and the BrightMart API under
`/shop`. Separate Vercel projects serve ContextIQ and BrightMart. The ContextIQ
Vercel project uses the repository root and proxies its same-origin API requests
to the Render service declared in the root `vercel.json`. The BrightMart cart
stays in the store browser until the user selects **Track in ContextIQ** or
**Check out with ContextIQ**.

1. In Vercel, import `Ganeshchaithanya/ContextIQ_V2.0-` and set the root directory to
   `brightmart`. Choose a free Hobby workspace and a project name. Note its
   production domain. Vercel reads the build settings from `brightmart/vercel.json`.
2. In Render, create a Blueprint from the same repository on `main`. Set
   `CONTEXTIQ_STORE_URL` to the Vercel production origin, including `https://`.
   Enter your `GROQ_API_KEY` in Render when prompted. Render generates the signing
   secret and runs the free web service.
3. Set `RENDER_APP_URL` in the BrightMart project's Production environment to the
   HTTPS origin of the Render service. Deploy from `main`. If you change either
   domain, update the corresponding environment variable on the other platform.
4. Import the same repository into a second Vercel project at its root for
   ContextIQ. Deploy from `main`. Add its production origin to Render as
   `CONTEXTIQ_APP_URL` so BrightMart handoffs open the Vercel site. If you change
   the Render service URL, update the two rewrites in the root `vercel.json`.
5. Verify `/api/config` on Render and ContextIQ's Vercel deployment, then open each site in a private browser
   window. Follow the [judge walkthrough](DEMO.md) through the kirana demo,
   signed cart handoff, and mock checkout. Share the two production URLs.

To enable Tara's optional language-model routing, add these Render environment variables:

| Key | Value |
| --- | --- |
| `LLM_PROVIDER` | `groq` |
| `GROQ_API_KEY` | A secret created in the [Groq console](https://console.groq.com/keys) |
| `GROQ_MODEL_SMALL` | `openai/gpt-oss-20b` |
| `GROQ_MODEL_LARGE` | `openai/gpt-oss-120b` |

Save and redeploy. `/api/config` reports whether a provider is configured.
Test Ask Tara with "What deserves my attention first?" The Ask API records
`routing: "llm"` when the provider returns a valid topic. Tara sends only
unrecognized questions to the provider for classification. Account records
and payment controls stay in ContextIQ. Use fictional demo details in questions.

The hosted demo uses fictional data and built-in mock payments. Leave PayPal
environment variables unset. Render's free service
can take time to wake and its local SQLite data can reset when the instance
restarts. Price checks run when invoked and while the tracking view is open.
