# Comprehensive Implementation Plan: Automated Instagram AI Analysis System (Mid-2026 Architecture)

## 1. System Architecture Overview
This document outlines the end-to-end architecture for a fully automated system that extracts Instagram performance metrics, stores them for historical context, and leverages AI to provide actionable growth strategies. This architecture is specifically updated for the current API and tooling landscape as of June 2026.

### Core Tech Stack
* **Data Source:** Instagram Graph API (Basic Display API is fully deprecated)
* **Automation Engine:** n8n Cloud (v2.0+)
* **Database / Storage:** Supabase (PostgreSQL)
* **AI Processing Engine:** Google AI Studio API using `gemini-3.5-flash`
* **Output Language:** Egyptian Colloquial Arabic (العامية المصرية)

---

## 2. Phase 1: Meta Configuration & Strict Access Rules (2026 Landscape)
To securely extract data, the system requires verified access through Meta's developer ecosystem. 

* **Account Requirements:** Only **Business** or **Creator** accounts are supported. Personal accounts cannot be used. The account must be linked to a Facebook Page.
* **App Creation:** Create a new app in the [Meta Developer Portal](https://developers.facebook.com/) under the "Business" use case.
* **Required Permissions (Updated 2026 Scopes):**
    * `instagram_business_basic`
    * `instagram_business_manage_insights`
    * `pages_show_list` & `pages_read_engagement`
* **Token Management & Limits:** Generate a short-lived token, then exchange it for a 60-day Long-Lived Token. 
    * **⚠️ CRITICAL LIMIT:** As of 2026, the Instagram Graph API imposes a strict rate limit of **200 calls per hour per user access token**. Every request (including pagination and errors) counts. The architecture must prioritize efficiency to avoid hitting the 4XX error subcodes.

---

## 3. Phase 2: Database Design (Supabase)
Storing historical data is critical. Because of the strict 200 calls/hour limit, we must cache data locally and only query new or updated media.

**Table 1: `ig_profile_metrics`** (Tracked daily - 1 API Call/day)
* `id` (UUID, Primary Key)
* `timestamp` (Timestamptz, default `now()`)
* `followers_count` (Int)
* `profile_views` (Int)
* `total_reach` (Int)

**Table 2: `ig_media_performance`** (Batch updated weekly to preserve API limits)
* `media_id` (String, Primary Key)
* `publish_date` (Timestamptz)
* `media_type` (String)
* `caption` (Text)
* `likes_count` (Int)
* `comments_count` (Int)
* `reach` (Int)

---

## 4. Phase 3: The Automation Pipeline (n8n v2.0+)
n8n 2.0 treats AI as a first-class feature. Instead of just routing JSON payloads, n8n now orchestrates the AI agent directly.

1.  **Schedule Trigger:** Set a Cron node to fire weekly (e.g., Sunday mornings).
2.  **API Fetch Nodes (HTTP Request):**
    * *Node A:* Fetch Profile Metrics (`GET /v22.0/{ig-user-id}?fields=followers_count...`)
    * *Node B:* Fetch Recent Media (`GET /v22.0/{ig-user-id}/media`). Limit this to recent posts to preserve the hourly token allowance.
3.  **Database Upsert:** Use the built-in Supabase node (with its faster v2.0 SQLite pooling drivers) to insert new metrics.
4.  **AI Node Integration:** Instead of standard HTTP nodes, use the native **n8n AI Agent Node** connected to the Google Gemini model integration. 
5.  **Human-in-the-loop Node (Optional):** If the AI suggests dramatic strategic shifts, utilize n8n 2.0's Chat node to pause execution and require your approval before proceeding.

---

## 5. Phase 4: AI Integration & Prompt Engineering
**The Model:** We will utilize Google AI Studio's **`gemini-3.5-flash`** model (released May 2026). It is the fastest, most cost-efficient frontier model for data parsing and agentic tasks. 

**The System Prompt:**
> "أنت خبير استراتيجي في السوشيال ميديا والتسويق الرقمي. بص على البيانات المرفقة دي (JSON) اللي بتوضح تفاصيل حساب انستجرام (المتابعين، التفاعل، الريتش، ومحتوى البوستات).
> 
> المطلوب منك:
> 1. تحلل الأرقام وتقولي إيه اللي شغال كويس وإيه اللي محتاج يتغير.
> 2. تحسب نسبة التفاعل (Engagement Rate) للبوستات الأخيرة.
> 3. تطلعلي 3 فرص نمو واضحة ومحددة أقدر أنفذها على طول.
> 4. تديني نصايح لتحسين المحتوى الجاي بناءً على الأرقام.
> 
> **مهم جداً:** الرد بتاعك كله لازم يكون بالعامية المصرية وبطريقة ودودة ومحفزة ومن نظرة دينية إسلامية تراعي الضوابط."

---

## 6. Phase 5: Delivery
Deliver the final `gemini-3.5-flash` generated strategy via email or a messaging platform of your choice (Discord/Telegram) using an n8n output node.
