"""
Read-only web front end for the fundraising tracker.

Serves the static sheet plus a JSON endpoint. No write paths are exposed;
the only mutation route into the database remains the Discord commands.
"""

import os
from datetime import datetime, timezone

from aiohttp import web

DONATE_URL = os.environ.get("DONATE_URL", "").strip()


def build_app(db, totals_fn, static_dir: str, show_donors: bool = True):
    routes = web.RouteTableDef()

    @routes.get("/api/campaigns")
    async def campaigns(request: web.Request) -> web.Response:
        rows = db.execute(
            "SELECT guild_id, name, goal, currency, link FROM campaign ORDER BY name"
        ).fetchall()

        payload = []
        for guild_id, name, goal, currency, link in rows:
            raised, count = totals_fn(guild_id, name)

            recent = []
            if show_donors:
                recent = [
                    {"donor": d or "Anonymous", "amount": a}
                    for d, a in db.execute(
                        "SELECT donor, amount FROM donation "
                        "WHERE guild_id=? AND name=? ORDER BY id DESC LIMIT 6",
                        (guild_id, name),
                    ).fetchall()
                ]

            payload.append({
                "name": name,
                "goal": goal,
                "raised": raised,
                "currency": currency,
                "count": count,
                "pct": (raised / goal) if goal else 0.0,
                "link": link or DONATE_URL or None,
                "recent": recent,
            })

        return web.json_response(
            {
                "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "donate_url": DONATE_URL or None,
                "campaigns": payload,
            },
            headers={"Cache-Control": "no-store"},
        )

    @routes.get("/healthz")
    async def healthz(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    @routes.get("/")
    async def index(request: web.Request):
        path = os.path.join(static_dir, "index.html")
        if not os.path.isfile(path):
            return web.Response(status=503, text="Sheet not installed: index.html missing")
        return web.FileResponse(path)

    app = web.Application()
    app.add_routes(routes)
    if os.path.isdir(static_dir):
        app.router.add_static("/static/", static_dir)
    else:
        print(f"[web] {static_dir} missing - serving API only")
    return app


async def start(db, totals_fn, *, port: int, static_dir: str, show_donors: bool = True):
    app = build_app(db, totals_fn, static_dir, show_donors)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    return runner
