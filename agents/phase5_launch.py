"""Phase 5 (Sell/deliver/get paid), step 1: go-to-market plan, store-page draft and launch posts.

    from agents.phase5_launch import agent
    update = agent(briefcase)   # {"drafts": {"phase5_launch": {...}}, "text_violations": [...], "tokens": n}

Nothing is posted or published. The store page goes live only through
payments.publish_listing(..., founder_approved=True) on the MOCKED store, and the founder
posts each launch post themselves, under their own name. The price shown is the Phase 4
draft's price when there is one; the agent never invents a price. Segment and channel
choices are claims (Phase 1 evidence or ASSUMPTION). Every text passes guardrails.check_text
(one rewrite, then flagged). Writes outputs/phase5_step1_launch.md (STUBBED until wired in).
"""

from __future__ import annotations

from typing import Any

from agents import phase2_6_shared as shared

AGENT = "phase5_launch"

NOTHING_POSTED = ("Draft only. Nothing has been posted or published: the founder edits, approves and posts each item "
                  "under their own name. Store hosting and checkout are MOCKED.")

SYSTEM = """You draft a launch plan for a founder's digital product. Be honest and plain: no praise, no invented numbers, no income or success promises.
Input: the founder's brief, the niche, numbered research evidence, and the proposed price (may be empty).
Items with "source" cite the evidence number they rest on, or null if nothing supports them. One fact per item.
Reply with JSON only:
{"segment":[{"text":"","source":null}],"positioning":"","channels":[{"text":"","source":null}],"launch_sequence":[""],
"store_page":{"title":"","description":"","bullets":[""]},
"launch_posts":[{"channel":"","text":""}]}
At most 3 segments, 3 channels, 5 launch steps and 3 posts.
Store page and posts: describe what the product does. No reviews, testimonials, user counts, ratings, urgency, countdowns, discounts that expire, or promises. Never write as a customer or another brand; posts are for the founder to post under their own name. Don't state a price.
Only describe features from the brief; never invent features, free trials, demos or other offers. Don't overstate the evidence ("many", "countless"): say what it shows."""


def agent(state: dict[str, Any]) -> dict[str, Any]:
    evidence = shared.phase1_evidence(state)
    commercial = ((state.get("drafts") or {}).get("phase4_commercial") or {}).get("pricing") or {}
    price_text = " ".join(str(commercial.get(k, "")).strip() for k in ("price", "currency")).strip()
    payload = {**shared.base_payload(state, evidence), "price": price_text}
    data, found, usage = shared.ask_guarded(AGENT, SYSTEM, payload, round_no=int(state.get("round") or 1), max_tokens=1100)

    segment = shared.claims_for(data.get("segment"), evidence, "segment", AGENT, limit=3)
    channels = shared.claims_for(data.get("channels"), evidence, "channels", AGENT, limit=3)
    sequence = shared.strings(data.get("launch_sequence"), limit=5, chars=200)
    sp = data.get("store_page") if isinstance(data.get("store_page"), dict) else {}
    store_page = {
        "title": shared.common.cut(sp.get("title", ""), 100),
        "description": shared.common.cut(sp.get("description", ""), 500),
        "bullets": shared.strings(sp.get("bullets"), limit=5, chars=160),
        "price": price_text or None,
    }
    posts = []
    for post in (data.get("launch_posts") if isinstance(data.get("launch_posts"), list) else [])[:3]:
        if isinstance(post, dict) and str(post.get("text", "")).strip():
            posts.append({"channel": shared.common.cut(post.get("channel", ""), 40), "text": shared.common.cut(post["text"], 600),
                          "posted": False})
    claims = segment + channels

    posts_md = "\n\n".join(f"### Post {i} ({p['channel'] or 'channel not stated'})\n\n{p['text']}" for i, p in enumerate(posts, 1))
    body = (
        f"> {NOTHING_POSTED}\n\n"
        "## Go-to-market\n\n"
        f"### Segment\n\n{shared.bullet_claims(segment)}\n\n"
        f"### Positioning\n\n{shared.common.cut(data.get('positioning', ''), 300) or '_Not stated._'}\n\n"
        f"### Channels\n\n{shared.bullet_claims(channels)}\n\n"
        "### Launch sequence\n\n" + ("\n".join(f"{i}. {s}" for i, s in enumerate(sequence, 1)) or "_None proposed._") + "\n\n"
        "## Store page (draft)\n\n"
        f"**{store_page['title'] or '_No title._'}**\n\n{store_page['description']}\n\n{shared.bullets(store_page['bullets'])}\n\n"
        f"Price: {price_text or '_not set: comes from the Phase 4 pricing draft once the founder approves it_'}\n\n"
        "Goes live only via `payments.publish_listing(..., founder_approved=True)` on the MOCKED store.\n\n"
        f"## Launch posts (drafts, not posted)\n\n{posts_md or '_None proposed._'}\n"
    )
    draft = {"segment": segment, "positioning": shared.common.cut(data.get("positioning", ""), 300), "channels": channels,
             "launch_sequence": sequence, "store_page": store_page, "launch_posts": posts, "posted": False}
    return shared.finish(state, AGENT, 5, 1, "launch", "go-to-market, store page and launch posts", body, draft, claims, found, usage)
