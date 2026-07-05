#!/usr/bin/env python3
"""Generate feed.xml (RSS 2.0 + iTunes namespace) from episodes.json."""
import json
import os
from email.utils import formatdate
from xml.sax.saxutils import escape
from datetime import datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(PROJ, "episodes.json")
FEED = os.path.join(PROJ, "feed.xml")


def rfc2822(iso):
    dt = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
    return formatdate(dt.timestamp(), usegmt=True)


def hms(seconds):
    s = int(seconds)
    return f"{s//3600:02d}:{s%3600//60:02d}:{s%60:02d}"


def main():
    with open(MANIFEST) as f:
        m = json.load(f)
    show = m["show"]
    items = []
    for ep in sorted(m["episodes"], key=lambda e: e["id"], reverse=True):
        items.append(f"""    <item>
      <title>{escape(ep['title'])}</title>
      <description>{escape(ep['description'])}</description>
      <guid isPermaLink="false">la-senal-ep{ep['id']}</guid>
      <pubDate>{rfc2822(ep['pubDate'])}</pubDate>
      <enclosure url="{escape(ep['url'])}" length="{ep['bytes']}" type="audio/mpeg"/>
      <itunes:duration>{hms(ep['duration_s'])}</itunes:duration>
      <itunes:episode>{int(ep['id'])}</itunes:episode>
      <itunes:episodeType>{'trailer' if ep['id'] == '000' else 'full'}</itunes:episodeType>
      <itunes:explicit>false</itunes:explicit>
    </item>""")
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(show['title'])}</title>
    <description>{escape(show['description'])}</description>
    <link>{escape(show['link'])}</link>
    <language>es-CO</language>
    <atom:link href="{escape(show['feed_url'])}" rel="self" type="application/rss+xml"/>
    <itunes:author>{escape(show['author'])}</itunes:author>
    <itunes:image href="{escape(show['image'])}"/>
    <itunes:category text="Education">
      <itunes:category text="Language Learning"/>
    </itunes:category>
    <itunes:explicit>false</itunes:explicit>
    <itunes:type>serial</itunes:type>
{os.linesep.join(items)}
  </channel>
</rss>
"""
    with open(FEED, "w") as f:
        f.write(feed)
    print(f"feed.xml written with {len(items)} episodes")


if __name__ == "__main__":
    main()
