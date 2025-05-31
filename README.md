This program will convert listenbrainz data to the spotify listening history format.
This allows you to import listenbrainz data into spotify analytics tools like stats.fm.

Songs imported from spotify will be ignored, as they are already in the spotify listening history format.
All other songs will be converted to the spotify listening history format, using the spotify API.

The first run will take a while, as it will need to fetch all new songs from the spotify API.
On subsequent runs, it will use the cached spotify data, which is stored in the `spotify_cache.json` file.

a .env files is required to run this program, with the following variables:
- `SPOTIFY_CLIENT_ID`: Your Spotify client ID
- `SPOTIFY_CLIENT_SECRET`: Your Spotify client secret
- `USERNAME`: Your chosen username
- `COUNTRY_CODE`: Country code for the user, e.g. 'US', 'GB', etc.


Your listenbrainz data should be stored in the data folder.
Any .json file in the data folder will be processed.
This includes sub directories inside the data folder.