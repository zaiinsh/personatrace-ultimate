# PersonaTrace v9 — live benchmark

Seeds run: 23 real public usernames + 3 nonexistent controls.
Total profiles across seeds: 149. Total wall time: 2345.9s (per-seed time budget 30s, parallel adapters, no keys, no cache).
Controls must return ~0 profiles; anything else would be a false-positive bug and is shown as-is.

| seed | profiles | edges | possible | wall (s) | fingerprint | timed-out adapters | degraded/other sources |
|---|---|---|---|---|---|---|---|
| octocat | 7 | 1 | 0 | 75.65 | 3f0ea1037750 | — | crtsh, discourse, dns, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| torvalds | 5 | 0 | 0 | 42.63 | 0941aff57185 | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| gaearon | 5 | 1 | 0 | 77.05 | 508cb73bf926 | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| sindresorhus | 7 | 2 | 0 | 90.46 | 7e8933c84309 | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| yyx990803 | 3 | 1 | 0 | 90.67 | d8520ccbe55a | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, tiktok, tiktok_web, wayback, x, x_web, youtube |
| defunkt | 7 | 1 | 0 | 90.03 | 5c22ec9e425e | — | crtsh, discourse, dns, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| mojombo | 16 | 12 | 0 | 107.24 | 2e5d0405459c | — | crtsh, discourse, dns, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| kelseyhightower | 6 | 1 | 0 | 61.98 | d8c566b54744 | — | crtsh, discourse, dns, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| btholt | 6 | 1 | 0 | 88.18 | 70deb73a1dbb | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| sarah_edo | 1 | 0 | 0 | 17.39 | 10532c58acad | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, tiktok, tiktok_web, wayback, x, youtube |
| github | 9 | 3 | 0 | 119.15 | 1893901a2b63 | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| microsoft | 6 | 1 | 0 | 82.47 | 37fdd20b8479 | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| google | 8 | 1 | 0 | 67.55 | 85817d821c74 | — | crtsh, discourse, dns, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| netflix | 6 | 2 | 0 | 88.11 | 8a5d57e8f6e8 | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| spotify | 7 | 1 | 0 | 71.55 | 8dbaf5faad1c | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| iamshaunjp | 2 | 1 | 0 | 62.57 | c720f21b8624 | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, tiktok, tiktok_web, wayback, x, x_web, youtube |
| bradtraversy | 5 | 2 | 0 | 88.4 | d6d7966cc78e | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, x_web, youtube |
| fireship-io | 2 | 1 | 0 | 70.98 | 4b22fe6fca32 | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, tiktok, tiktok_web, wayback, x, x_web, youtube |
| ThePrimeagen | 9 | 4 | 0 | 137.37 | 36ffc449bb61 | — | crtsh, discourse, dns, instagram, instagram_web, linkedin, reddit, tiktok, tiktok_web, wayback, x, youtube |
| tj | 5 | 0 | 0 | 78.75 | e6da229817e8 | — | crtsh, discourse, dns, hackernews, instagram, instagram_web, linkedin, reddit, telegram, tiktok, wayback, x, youtube |
| mitchellh | 16 | 12 | 0 | 108.92 | 3671ba9e4863 | — | crtsh, discourse, dns, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| antirez | 11 | 6 | 0 | 431.17 | 41a307cb6a20 | — | crtsh, discourse, dns, instagram, instagram_web, linkedin, reddit, tiktok, wayback, x, youtube |
| mrdoob | 0 | 0 | 0 | 133.24 | e3b0c44298fc | — | bluesky, crtsh, discourse, dns, github, gitlab, hackernews, instagram, instagram_web, linkedin, mastodon, reddit, stackoverflow, telegram, tiktok, tiktok_web, wayback, x, x_web, youtube |
| pt-no-such-user-9f3k2x7q (CONTROL) | 0 | 0 | 0 | 39.54 | e3b0c44298fc | — | bluesky, crtsh, discourse, dns, github, gitlab, hackernews, instagram, instagram_web, linkedin, mastodon, reddit, stackoverflow, telegram, tiktok, tiktok_web, wayback, x, x_web, youtube |
| zzqxv-not-a-person-4411 (CONTROL) | 0 | 0 | 0 | 12.15 | e3b0c44298fc | — | bluesky, crtsh, discourse, dns, gitlab, hackernews, instagram, instagram_web, linkedin, reddit, stackoverflow, telegram, tiktok, tiktok_web, wayback, x, x_web, youtube |
| no-such-handle-xqzw-778 (CONTROL) | 0 | 0 | 0 | 12.72 | e3b0c44298fc | — | bluesky, crtsh, discourse, dns, gitlab, hackernews, instagram, instagram_web, linkedin, reddit, stackoverflow, telegram, tiktok, tiktok_web, wayback, x, x_web, youtube |

Notes: numbers are the real live outcome at run time. A seed with few profiles usually means its owner is quiet on the free sources PersonaTrace checks (GitHub/GitLab/Bluesky/Mastodon/HN/StackOverflow/Telegram + site checks), not that the person has no accounts. Gated platforms (Instagram/X/TikTok/Reddit/YouTube full data) are not_checked without the investigator's own keys and are excluded from this no-key benchmark by design.
