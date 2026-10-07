"""
Read-only web front end for the fundraising tracker.

Serves the static sheet plus a JSON endpoint. No write paths are exposed;
the only mutation route into the database remains the Discord commands.
"""

import io
import os
import re
import time
from datetime import datetime, timezone

import aiohttp
import qrcode
import qrcode.image.svg
from aiohttp import web

DONATE_URL = os.environ.get("DONATE_URL", "").strip()

# Every QR code the sheet shows, by name. Each link can be overridden (or
# blanked to hide its card) with the env var named here.
QR_LINKS = {
    # Card / Givebutter donations: the per-campaign default link.
    "donate": DONATE_URL,
    "venmo": os.environ.get(
        "VENMO_URL",
        "https://www.paypal.com/qrcodes/venmocs/da49c07b-2aeb-42b7-9cd4-731507b6012b"
        "?created=1791391114",
    ).strip(),
    "discord": os.environ.get("DISCORD_URL", "https://discord.gg/F7kM7ardMs").strip(),
    "membership": os.environ.get(
        "MEMBERSHIP_URL", "https://columbiagadgetworks.org/membership/"
    ).strip(),
}

# The CGW website's calendar endpoint (GET /api/calendar on the site's
# Worker). Fetched server-side so the page makes no cross-site request.
# Empty until the site serves it; the sheet then shows the standing schedule.
CALENDAR_API_URL = os.environ.get("CALENDAR_API_URL", "").strip()
CALENDAR_CACHE_SECONDS = 600
_calendar_cache: dict[str, tuple[float, dict]] = {}


def _qr_svg(url: str) -> str | None:
    """Rendered once at startup - the links are fixed for the process lifetime."""
    if not url:
        return None
    qr = qrcode.QRCode(border=4, box_size=10)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8").replace('fill="#000000"', 'fill="#101A22"')


QR_SVGS = {name: _qr_svg(url) for name, url in QR_LINKS.items()}


async def _fetch_calendar(month: str) -> dict:
    """One month from the website's calendar API, cached for a few minutes."""
    hit = _calendar_cache.get(month)
    if hit and time.monotonic() - hit[0] < CALENDAR_CACHE_SECONDS:
        return hit[1]
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            CALENDAR_API_URL,
            params={"from": month, "months": "1"},
            headers={"accept": "application/json"},
        ) as res:
            data = await res.json(content_type=None)
    if not isinstance(data, dict) or not data.get("ok"):
        raise ValueError((data or {}).get("error", "unavailable"))
    events = [
        {k: e.get(k) for k in ("day", "start", "end", "allDay", "title", "location")}
        for e in data.get("events", [])[:300]
        if isinstance(e, dict) and e.get("day") and e.get("title")
    ]
    payload = {"ok": True, "from": month, "events": events}
    _calendar_cache[month] = (time.monotonic(), payload)
    if len(_calendar_cache) > 24:
        _calendar_cache.pop(next(iter(_calendar_cache)))
    return payload


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
                # Which QR cards to show; the images live at /qr/<name>.svg.
                "links": {name: url or None for name, url in QR_LINKS.items()},
                "campaigns": payload,
            },
            headers={"Cache-Control": "no-store"},
        )

    @routes.get("/healthz")
    async def healthz(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    def qr_response(name: str) -> web.Response:
        svg = QR_SVGS.get(name)
        if not svg:
            raise web.HTTPNotFound()
        return web.Response(
            text=svg,
            content_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @routes.get("/qr.svg")
    async def qr_svg(request: web.Request) -> web.Response:
        # Older copies of the sheet still ask for the donate code here.
        return qr_response("donate")

    @routes.get("/qr/{name}.svg")
    async def qr_named(request: web.Request) -> web.Response:
        return qr_response(request.match_info["name"])

    @routes.get("/api/calendar")
    async def calendar(request: web.Request) -> web.Response:
        month = request.query.get("from", "")
        if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", month):
            return web.json_response({"ok": False, "error": "bad-month"}, status=400)
        if not CALENDAR_API_URL:
            return web.json_response(
                {"ok": False, "error": "not-configured", "events": []},
                headers={"Cache-Control": "no-store"},
            )
        try:
            data = await _fetch_calendar(month)
        except Exception as e:  # upstream down or unreadable: page falls back
            print(f"[web] calendar {month}: {e!r}")
            return web.json_response(
                {"ok": False, "error": "unavailable", "events": []},
                status=502,
                headers={"Cache-Control": "no-store"},
            )
        return web.json_response(
            data, headers={"Cache-Control": f"public, max-age={CALENDAR_CACHE_SECONDS}"}
        )

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
