import os
import json
import re
import requests
from datetime import datetime
from urllib.parse import quote
from base64 import b64encode
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ========== CONFIG ==========
CACHE_FILE = "spotify_api_cache.json"
OUTPUT_FILE = "spotify_streaming_history.json"

# At the top of the file
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
USERNAME = os.getenv("USERNAME", "your_username")
COUNTRY_CODE = os.getenv("COUNTRY_CODE", "XX")

if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
    raise ValueError(
        "Please set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET environment variables"
    )


# ========== AUTH ==========
def get_spotify_access_token():
    auth_str = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
    b64_auth = b64encode(auth_str.encode()).decode()
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "client_credentials"}
    response = requests.post(
        "https://accounts.spotify.com/api/token", headers=headers, data=data
    )
    response.raise_for_status()
    return response.json()["access_token"]


# ========== HELPERS ==========
def normalize_string(s):
    s = s.lower()
    s = re.sub(r"\s*\(feat\.?.*?\)", "", s)
    s = re.sub(r"\s*\[.*?\]", "", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def convert_lb_entry_to_spotify_format(entry, username, country_code):
    meta = entry["track_metadata"]
    info = meta.get("additional_info", {})

    ts_raw = datetime.utcfromtimestamp(entry["listened_at"]).isoformat() + "Z"
    artist_raw = meta.get("artist_name", "").strip()
    track_raw = meta.get("track_name", "").strip()
    album_raw = meta.get("release_name", "").strip()
    spotify_id = info.get("spotify_id")

    spotify_uri = (
        "spotify:track:" + spotify_id.split("/")[-1]
        if spotify_id and "open.spotify.com/track/" in spotify_id
        else None
    )

    return {
        "ts": ts_raw,
        "username": username,
        "platform": "ListenBrainz Importer",
        "ms_played": info.get("duration_ms", 0),
        "conn_country": country_code,
        "ip_addr_decrypted": None,
        "user_agent_decrypted": None,
        "master_metadata_track_name": track_raw,
        "master_metadata_album_artist_name": artist_raw,
        "master_metadata_album_album_name": album_raw,
        "spotify_track_uri": spotify_uri,
        "episode_name": None,
        "episode_show_name": None,
        "spotify_episode_uri": None,
        "reason_start": "trackdone",
        "reason_end": None,
        "shuffle": False,
        "skipped": False,
        "offline": True,
        "offline_timestamp": entry["listened_at"] * 1000,
        "incognito_mode": False,
    }


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def try_alternate_queries(artist_norm, track_norm, token, cache):
    alternates = [
        (artist_norm, track_norm),
        ("", track_norm),
        (artist_norm.split(" feat")[0], track_norm),
        (artist_norm, re.sub(r"\s*\(.*?\)|\[.*?\]", "", track_norm)),
        (artist_norm, track_norm.replace("remastered", "").strip()),
    ]
    for alt_artist, alt_track in alternates:
        if not alt_track.strip():
            continue
        result = query_spotify_api(alt_artist.strip(), alt_track.strip(), token, cache)
        if result:
            return result
    return None


def query_spotify_api(artist, track, token, cache):
    base_key = f"{artist}|{track}"
    if base_key in cache:
        print(f"🔁 [CACHE] {artist} – {track}")
        return cache[base_key]

    headers = {"Authorization": f"Bearer {token}"}
    queries = [
        f"{track} artist:{artist}",
        f"{track} {artist}",
        f"track:{track}",
    ]

    for i, query in enumerate(queries):
        try:
            encoded = quote(query)
            url = f"https://api.spotify.com/v1/search?q={encoded}&type=track&limit=1"
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                items = response.json().get("tracks", {}).get("items", [])
                if items:
                    item = items[0]
                    result = {
                        "spotify_track_uri": item["uri"],
                        "album_name": item["album"]["name"],
                    }
                    cache[base_key] = result
                    save_cache(cache)
                    print(f"✅ [API] Found: {artist} – {track} (pattern {i+1})")
                    return result
        except Exception as e:
            print(
                f"🔥 [ERROR] Spotify API error (pattern {i+1}): {artist} – {track}: {e}"
            )

    print(f"❌ [API] Not found: {artist} – {track}")
    cache[base_key] = None
    save_cache(cache)
    return None


def all_jsonl_files_in(folder):
    for root, _, files in os.walk(folder):
        for file in files:
            if file.endswith(".jsonl"):
                yield os.path.join(root, file)


# ========== MAIN LOGIC ==========
def convert_with_spotify_api(
    data_folder, unknowns_file, username="your_username", country_code="XX"
):
    token = get_spotify_access_token()
    cache = load_cache()
    unknowns = set()
    output_data = []
    open(unknowns_file, "w").close()

    processed_count = 0
    skipped_spotify = 0

    for path in all_jsonl_files_in(data_folder):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    meta = entry["track_metadata"]
                    info = meta.get("additional_info", {})

                    if info.get("music_service") == "spotify.com":
                        skipped_spotify += 1
                        continue

                    ts_raw = (
                        datetime.utcfromtimestamp(entry["listened_at"]).isoformat()
                        + "Z"
                    )
                    artist_raw = meta.get("artist_name", "").strip()
                    track_raw = meta.get("track_name", "").strip()
                    album_raw = meta.get("release_name", "").strip()

                    artist_norm = normalize_string(artist_raw)
                    track_norm = normalize_string(track_raw)

                    lb_spotify_id = info.get("spotify_id")
                    if lb_spotify_id and "open.spotify.com/track/" in lb_spotify_id:
                        record = convert_lb_entry_to_spotify_format(
                            entry, username, country_code
                        )
                        output_data.append(record)
                        processed_count += 1
                        print(
                            f"🎷 [LB] Used ListenBrainz URI: {record['master_metadata_album_artist_name']} – {record['master_metadata_track_name']}"
                        )
                        continue

                    else:
                        api_result = try_alternate_queries(
                            artist_norm, track_norm, token, cache
                        )

                        if api_result:
                            spotify_uri = api_result["spotify_track_uri"]
                            album_name = api_result["album_name"]
                        else:
                            spotify_uri = None
                            album_name = album_raw
                            unknowns.add(f"{artist_raw} – {track_raw}")

                    record = {
                        "ts": ts_raw,
                        "username": username,
                        "platform": "ListenBrainz Importer",
                        "ms_played": info.get("duration_ms", 0),
                        "conn_country": country_code,
                        "ip_addr_decrypted": None,
                        "user_agent_decrypted": None,
                        "master_metadata_track_name": track_raw,
                        "master_metadata_album_artist_name": artist_raw,
                        "master_metadata_album_album_name": album_name,
                        "spotify_track_uri": spotify_uri,
                        "episode_name": None,
                        "episode_show_name": None,
                        "spotify_episode_uri": None,
                        "reason_start": "trackdone",
                        "reason_end": None,
                        "shuffle": False,
                        "skipped": False,
                        "offline": True,
                        "offline_timestamp": entry["listened_at"] * 1000,
                        "incognito_mode": False,
                    }

                    output_data.append(record)
                    processed_count += 1

                    if processed_count % 100 == 0:
                        print(f"📦 Processed {processed_count} songs...")

                except Exception as e:
                    print(f"🔥 [ERROR] Processing error: {e}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    with open(unknowns_file, "w", encoding="utf-8") as out:
        out.write("\n".join(sorted(unknowns)))

    # Final stats
    unique_artists = set()
    unique_tracks = set()
    total_ms = 0
    total_records = 0

    for record in output_data:
        total_records += 1
        unique_artists.add(record.get("master_metadata_album_artist_name", ""))
        unique_tracks.add(record.get("master_metadata_track_name", ""))
        total_ms += record.get("ms_played", 0)

    total_minutes = total_ms // 60000
    hours = total_minutes // 60
    minutes = total_minutes % 60

    print("\n📊 ====== STATS ======")
    print(f"✅ Converted:         {processed_count}")
    print(f"⏭️  Skipped Spotify:    {skipped_spotify}")
    print(f"🎨 Unique artists:    {len(unique_artists)}")
    print(f"🎵 Unique tracks:     {len(unique_tracks)}")
    print(f"⏱️  Total play time:   {hours}h {minutes}m")
    print(f"❗ Unknown tracks:     {len(unknowns)}")
    print(f"💾 Output file:        {OUTPUT_FILE}")
    print(f"📼 Cache file:         {CACHE_FILE}")
    print(f"🗃️  Unknowns list:      {unknowns_file}")


# ========== USAGE ==========
convert_with_spotify_api(
    data_folder="data",
    unknowns_file="unknown_songs.txt",
    username=USERNAME,
    country_code=COUNTRY_CODE,
)
