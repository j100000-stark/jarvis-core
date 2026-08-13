---
name: Groq Cloudflare block
description: Groq (and likely OpenRouter) sit behind Cloudflare; Python's default urllib User-Agent triggers CF error 1010 (403 Forbidden) before the request reaches the API.
---

## Symptom
HTTP 403, response body is `error code: 1010` (a Cloudflare page, not a Groq API error). The LLM API key is correct; Cloudflare blocks the connection at the CDN layer.

## Root cause
Python's default `urllib` User-Agent string (`Python-urllib/3.x`) is flagged by Cloudflare's bot-detection WAF. The request never reaches Groq's servers.

## Fix
Added `"User-Agent": "groq-python/0.11.0"` to the headers dict in `OpenAICompatibleTransport.chat_complete()` in `jarvis/agent/remote_llm.py`.

**Why this header**: Cloudflare allows known SDK UA strings. `groq-python/0.11.0` is the official Groq Python SDK UA. `python-httpx/0.27.0` also works. The urllib default does not.

## Also fixed in same edit
`HTTPError` handler now reads `error.read()` and appends the first 300 chars of the response body to the exception message. Previously the handler only captured `error.code` and `error.reason`, silently discarding the body (which is why the CF 1010 text was never visible in logs).

## How to apply
Any future `LLMTransport` implementation that uses `urllib` (or any HTTP client) must include a non-bot User-Agent. Applies to all providers behind Cloudflare: Groq, OpenRouter, possibly others.
