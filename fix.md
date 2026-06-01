# Root Cause & Fix Report — Deployment LLM Connection Errors

## 1. Root Cause Analysis

When the application was deployed, the agent returned no output and threw a `Subsystem fault [Error: ollama: All connection attempts failed]` error.

This was caused by a combination of two issues:

1. **Ignored `.env` File & Missing Deployment Environment Variables**:
   The `.env` file (which contains the API keys like `GROQ_API_KEY`, etc.) is listed in `.gitignore` and is not uploaded to the deployed cloud server. If the keys are not explicitly configured in the hosting provider's (e.g. Render) dashboard environment variables, the system fails to register cloud LLM providers (Groq, Cerebras, OpenRouter).

2. **Unconditional Ollama Fallback (Locahost Only)**:
   - When no cloud API keys are registered, the system falls back to `ollama` as the only provider.
   - Since `ollama` defaults to `http://localhost:11434`, it runs locally but fails on a deployed cloud server.
   - Even if cloud providers *are* registered but fail (e.g., due to an invalid key or a temporary rate limit), the manager falls back to `ollama`, which also fails because localhost is unreachable.

3. **Masked Error Reporting**:
   The `ProviderManager` had a bug where the `last_error` was overwritten by whichever provider failed last in the fallback chain. Because `ollama` was always tried last, any meaningful API key configuration errors from `groq`, `cerebras`, or `openrouter` (e.g. `401 Unauthorized`) were completely overwritten, hiding the true configuration problem.

---

## 2. Implemented Fixes

### A. Environment-Aware Ollama Registration
Modified [manager.py](file:///c:/friday/backend/providers/manager.py) to detect if the application is running in a deployed environment (by checking for environment variables like `RENDER`, `PORT`, `PRODUCTION`, etc.).
- If running in a deployed environment and the configured `OLLAMA_URL` is pointing to `localhost` or `127.0.0.1`, the system **automatically skips** registering `ollama` as a default fallback.
- This prevents useless localhost connections and misleading errors.

### B. Cumulative Error Logging
Updated both `generate` and `stream` methods in [manager.py](file:///c:/friday/backend/providers/manager.py) to accumulate errors from **all** attempted providers in a list, rather than overwriting `last_error`.
- If all providers fail, the system now returns a list of all errors (e.g. `groq: 401 Unauthorized; ollama: All connection attempts failed`), allowing direct insight into whether it was a configuration or a network issue.
- If no providers could be registered due to missing API keys, it raises a clear error: `"No usable LLM providers registered. Please check that you configured GROQ_API_KEY, CEREBRAS_API_KEY, or OPENROUTER_API_KEY in your environment."`

### C. Dynamic Ollama Health Check
Modified [ollama.py](file:///c:/friday/backend/providers/ollama.py) to extract the origin from the configured `base_url` for the health check endpoint, rather than hardcoding `http://localhost:11434/api/tags`.

---

## 3. How to Resolve in Your Deployment

To make sure your deployed application works:

1. **Set your API keys in the deployment dashboard**:
   Go to your hosting provider's dashboard (e.g., Render Dashboard > Environment tab) and configure the environment variables:
   - `GROQ_API_KEY` (e.g., `gsk_...`)
   - `FRIDAY_LLM_PROVIDER` (e.g., `groq`)
   - `SUPABASE_URL` and `SUPABASE_KEY` (if using Supabase)

2. **Redeploy**:
   Once the variables are set, trigger a new deployment. The system will now correctly register and use your cloud provider.
