"""Download Maigret's official site list (8,232 sites) into curated_maigret.json."""
import json, urllib.request
URL = "https://raw.githubusercontent.com/soxoj/maigret/main/maigret/resources/data.json"
with urllib.request.urlopen(URL, timeout=60) as r:
    data = json.load(r)
json.dump(data, open("curated_maigret.json", "w"), indent=1)
print(f"Maigret sites: {len(data.get('sites', {}))} written to curated_maigret.json")
