# Minion Rush API calls

Generated 2026-11-26 18:37:43 from 2 session(s), 749 recorded exchanges.

Every row is a distinct endpoint signature (numeric ids, UUIDs and long hashes are templated).
Credential headers are redacted **only here** - `Contents/` keeps the exact bytes.

## Game API

| Method | Host | Path template | Calls | Statuses | Sample |
| --- | --- | --- | --- | --- | --- |
| GET | fed.gold0029.gameloft.com | `/v1/assets/mru:7094:85784:13.4.0f:android:googleplay/{id}` | 356 | 302 x356 | 001-GET-fed.gold0029.gameloft.com-v1-assets-mru-7094-85784-13.4.0f-android.res.txt |
| GET | iris16-gold.gameloft.com | `/mru/{id}` | 356 | 200 x356 | 002-GET-iris16-gold.gameloft.com-mru-id.res.txt |

## Assets and CDN downloads

| Method | Host | Path template | Calls | Statuses | Sample |
| --- | --- | --- | --- | --- | --- |
| GET | pagead2.googlesyndication.com | `/pagead/gen_204?zx={v}&id={v}&event={v}&p={v}&rtype={v}&lat_ms={v}&e_lat_ms={v}&e_l={v}&osv={v}&req_id={v}&pn={v}&js={v}` | 2 | 204 x2 | 003-GET-pagead2.googlesyndication.com-pagead-gen_204-zx-v-id-v-event-v-p-v.res.txt |

## Analytics / telemetry

| Method | Host | Path template | Calls | Statuses | Sample |
| --- | --- | --- | --- | --- | --- |
| POST | cdp.cloud.unity3d.com | `/v1/events` | 18 | 200 x18 | 004-POST-cdp.cloud.unity3d.com-v1-events.res.txt |
| GET | googleads.g.doubleclick.net | `/mads/static/mad/sdk/native/{id}` | 3 | 200 x3 | 005-GET-googleads.g.doubleclick.net-mads-static-mad-sdk-native-id.res.txt |
| GET | ae.iads.unity3d.com | `/logs?data={v}` | 2 | 204 x2 | 006-GET-ae.iads.unity3d.com-logs-data-v.res.txt |
| GET | firebase-settings.crashlytics.com | `/spi/v2/platforms/android/gmp/1%3A897486707421%3Aandroid%3A4041000649f7af0d7f1934/settings?build_version={v}&display_version={v}` | 1 | 200 x1 | 007-GET-firebase-settings.crashlytics.com-spi-v2-platforms-android-gmp-1-3.res.txt |
| GET | firebase-settings.crashlytics.com | `/spi/v2/platforms/android/gmp/1:897486707421:android:4041000649f7af0d7f1934/settings?instance={v}&build_version={v}&display_version={v}&source={v}` | 1 | 200 x1 | 008-GET-firebase-settings.crashlytics.com-spi-v2-platforms-android-gmp-1-8.res.txt |
| GET | googleads.g.doubleclick.net | `/favicon.ico` | 1 | 200 x1 | 009-GET-googleads.g.doubleclick.net-favicon.ico.res.txt |
| GET | googleads.g.doubleclick.net | `/mads/static/mad/sdk/native/production/{id}?n={v}&lv={v}` | 1 | 200 x1 | 010-GET-googleads.g.doubleclick.net-mads-static-mad-sdk-native-production-.res.txt |
| GET | googleads.g.doubleclick.net | `/mads/static/sdk/native/{id}` | 1 | 200 x1 | 011-GET-googleads.g.doubleclick.net-mads-static-sdk-native-id.res.txt |
| GET | o-iab-notifications.mediation.unity3d.com | `/nurl?request={v}&auctionId={v}&ats={v}&appKey={v}` | 1 | 204 x1 | 012-GET-o-iab-notifications.mediation.unity3d.com-nurl-request-v-auctionId.res.txt |
| POST | config.uca.cloud.unity3d.com | `/` | 1 | 200 x1 | 013-POST-config.uca.cloud.unity3d.com.res.txt |
| POST | firebaseinstallations.googleapis.com | `/v1/projects/dm2-unity/installations` | 1 | 200 x1 | 014-POST-firebaseinstallations.googleapis.com-v1-projects-dm2-unity-instal.res.txt |
| POST | firebaselogging-pa.googleapis.com | `/v1/firelog/legacy/batchlog` | 1 | 200 x1 | 015-POST-firebaselogging-pa.googleapis.com-v1-firelog-legacy-batchlog.res.txt |
| POST | firebaselogging.googleapis.com | `/v0cc/log/batch?format={v}` | 1 | 200 x1 | 016-POST-firebaselogging.googleapis.com-v0cc-log-batch-format-v.res.txt |

## Other

| Method | Host | Path template | Calls | Statuses | Sample |
| --- | --- | --- | --- | --- | --- |
| POST | api.helpshift.com | `/events/v1/gameloft/websdk/` | 1 | 200 x1 | 017-POST-api.helpshift.com-events-v1-gameloft-websdk.res.txt |
| POST | api.helpshift.com | `/websdk/gameloft/sdk-data` | 1 | 404 x1 | 018-POST-api.helpshift.com-websdk-gameloft-sdk-data.res.txt |

## Hosts seen

| Host | Exchanges |
| --- | --- |
| fed.gold0029.gameloft.com | 356 |
| iris16-gold.gameloft.com | 356 |
| cdp.cloud.unity3d.com | 18 |
| googleads.g.doubleclick.net | 6 |
| ae.iads.unity3d.com | 2 |
| api.helpshift.com | 2 |
| firebase-settings.crashlytics.com | 2 |
| pagead2.googlesyndication.com | 2 |
| config.uca.cloud.unity3d.com | 1 |
| firebaseinstallations.googleapis.com | 1 |
| firebaselogging-pa.googleapis.com | 1 |
| firebaselogging.googleapis.com | 1 |
| o-iab-notifications.mediation.unity3d.com | 1 |
